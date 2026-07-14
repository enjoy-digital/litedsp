#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Golden-model test harness for LiteDSP.

Provides stream stimulus/capture generators with randomized backpressure (so every block is
exercised under valid/ready stalls), a small simulation runner, NumPy fixed-point helpers
that mirror ``litedsp.common`` bit-for-bit, and an SNR metric for comparing simulation output
against the NumPy reference models in ``test/models.py``.
"""

import os
import random

import numpy as np

from migen import run_simulation, passive

# Seed Plumbing ------------------------------------------------------------------------------------
#
# All default harness seeds derive from LITEDSP_SEED, so the whole suite can be re-run on a
# different randomization (nightly seed-rotation campaigns) while staying reproducible:
# failures report the seed; re-run with LITEDSP_SEED=<seed> to reproduce.

SEED = int(os.environ.get("LITEDSP_SEED", "0"))

# Stream Stimulus / Capture ------------------------------------------------------------------------

@passive
def stream_driver(endpoint, samples, fields, seed=None, throttle=0.0):
    """Drive ``samples`` into ``endpoint`` (a sink), honoring ready and inserting random gaps.

    ``samples`` is a list of dicts keyed by the names in ``fields``. ``throttle`` is the
    probability of inserting an idle (valid=0) cycle before each sample. Marked ``@passive`` so
    the simulation ends when the (active) capture finishes — over-feeding the driver is safe.
    """
    prng = random.Random(SEED if seed is None else seed)
    for sample in samples:
        while throttle and (prng.random() < throttle):
            yield endpoint.valid.eq(0)
            yield
        for f in fields:
            yield getattr(endpoint, f).eq(int(sample[f]))
        yield endpoint.valid.eq(1)
        yield
        while (yield endpoint.ready) == 0:
            yield
    yield endpoint.valid.eq(0)

def stream_capture(endpoint, captured, n, fields, seed=None, ready_rate=1.0):
    """Capture ``n`` samples from ``endpoint`` (a source) into ``captured`` (a list of dicts).

    ``ready_rate`` is the probability of asserting ready on each cycle (randomized backpressure).
    """
    prng = random.Random((SEED + 1) if seed is None else seed)
    while len(captured) < n:
        yield endpoint.ready.eq(1 if (prng.random() < ready_rate) else 0)
        yield
        if (yield endpoint.valid) and (yield endpoint.ready):
            sample = {}
            for f in fields:
                sample[f] = (yield getattr(endpoint, f))
            captured.append(sample)
    yield endpoint.ready.eq(0)

def run_stream(dut, sink_samples, n_out, sink_fields, source_fields,
    sink_throttle=0.25, source_ready_rate=0.75, sink_seed=None, source_seed=None, extra=None,
    vcd=None, reset_at=None):
    """Run ``dut`` feeding ``sink_samples`` and capturing ``n_out`` outputs.

    ``sink_samples`` may be ``None`` for source-only blocks (e.g. NCO). ``extra`` is an
    optional list of additional generators (e.g. control sequencing). ``reset_at`` pulses
    ``dut.reset`` (``@ResetInserter()`` blocks) at that cycle — for reset-mid-stream fuzzing.
    Returns the captured list of dicts.
    """
    captured   = []
    generators = []
    if sink_samples is not None:
        generators.append(stream_driver(dut.sink, sink_samples, sink_fields,
            seed=sink_seed, throttle=sink_throttle))
    generators.append(stream_capture(dut.source, captured, n_out, source_fields,
        seed=source_seed, ready_rate=source_ready_rate))
    if extra is not None:
        generators += extra
    if reset_at is not None:
        generators.append(reset_pulse(dut, reset_at))
    run_simulation(dut, generators, vcd_name=vcd)
    return captured

@passive
def reset_pulse(dut, at_cycle, width=1):
    """Pulse ``dut.reset`` for ``width`` cycles at ``at_cycle`` (reset-mid-stream fuzzing)."""
    for _ in range(at_cycle):
        yield
    yield dut.reset.eq(1)
    for _ in range(width):
        yield
    yield dut.reset.eq(0)

# Capture Helpers ----------------------------------------------------------------------------------

def to_signed(values, width):
    """Reinterpret unsigned captured values as signed ``width``-bit (idempotent)."""
    if width >= 63:
        # Exceeds int64 (e.g. Goertzel's 2*SW power output): use Python ints (object dtype).
        mask = (1 << width) - 1
        return np.array([(v & mask) - (1 << width) if (v & mask) >> (width - 1) else (v & mask)
                         for v in (int(x) for x in np.atleast_1d(values))], dtype=object)
    values = np.asarray(values, dtype=np.int64) & ((1 << width) - 1)
    return np.where(values >= (1 << (width-1)), values - (1 << width), values)

def column(captured, field, width=None):
    """Extract one field from a list of captured sample dicts as a NumPy array.

    If ``width`` is given, the values are reinterpreted as signed ``width``-bit.
    """
    values = np.array([s[field] for s in captured], dtype=np.int64)
    return to_signed(values, width) if width is not None else values

def iq_complex(captured, i="i", q="q"):
    """Extract captured I/Q samples as a complex NumPy array."""
    return column(captured, i) + 1j*column(captured, q)

# NumPy Fixed-Point Helpers (mirror litedsp.common) ------------------------------------------------

def np_rounded(value, shift):
    """Arithmetic right-shift with round-half-up, matching ``litedsp.common.rounded``."""
    value = np.asarray(value, dtype=np.int64)
    if shift == 0:
        return value
    return (value + (1 << (shift - 1))) >> shift

def np_saturated(value, out_width):
    """Clamp to signed ``out_width`` range, matching ``litedsp.common.saturated``."""
    hi =  (1 << (out_width - 1)) - 1
    lo = -(1 << (out_width - 1))
    return np.clip(np.asarray(value, dtype=np.int64), lo, hi)

def np_scaled(value, shift, out_width):
    """Round then saturate, matching ``litedsp.common.scaled`` (returns result only)."""
    return np_saturated(np_rounded(value, shift), out_width)

# Metrics ------------------------------------------------------------------------------------------

def snr_db(reference, measured):
    """Signal-to-noise ratio (dB) of ``measured`` vs ``reference`` (real or complex arrays)."""
    reference = np.asarray(reference)
    measured  = np.asarray(measured)
    signal    = np.sum(np.abs(reference)**2)
    noise     = np.sum(np.abs(measured - reference)**2)
    if noise == 0:
        return np.inf
    return 10*np.log10(signal/noise)

def assert_snr(testcase, reference, measured, min_db, msg=""):
    """Gate an SNR measurement (the one obvious way — avoids computed-but-unasserted metrics)."""
    snr = snr_db(reference, measured)
    testcase.assertGreaterEqual(snr, min_db,
        f"{msg + ': ' if msg else ''}SNR {snr:.1f} dB < {min_db} dB (LITEDSP_SEED={SEED})")
    return snr

def measure_lag(reference, measured, max_lag=None):
    """Sample lag of ``measured`` vs ``reference`` (argmax of cross-correlation).

    Used to verify a block's declared ``self.latency`` (sample-domain) against simulation.
    """
    reference = np.asarray(reference, dtype=float)
    measured  = np.asarray(measured,  dtype=float)
    n = min(len(reference), len(measured))
    reference, measured = reference[:n], measured[:n]
    if max_lag is None:
        max_lag = n - 1
    corr = [np.dot(measured[lag:n], reference[:n - lag]) for lag in range(max_lag + 1)]
    return int(np.argmax(corr))
