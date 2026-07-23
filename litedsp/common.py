#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Shared layouts and fixed-point helpers for LiteDSP.

All LiteDSP blocks operate on signed two's-complement fixed-point samples in Qm.n format
(``m`` integer bits including sign, ``n`` fractional bits, total width ``m + n``). The
default sample format is Q1.15 (16-bit, range [-1.0, +1.0)), matching typical RF data paths.

Streaming uses LiteX ``stream.Endpoint``: real-valued blocks carry a single ``data`` field,
complex (I/Q) blocks carry ``i`` and ``q`` fields (see :func:`real_layout` / :func:`iq_layout`).

Downsizing (after a multiply or accumulation) must go through :func:`rounded` then
:func:`saturated` (or :func:`scaled`, which does both) so every block handles scaling and
overflow consistently instead of silently truncating/wrapping.
"""

from migen import *

from litex.soc.interconnect.csr import CSRStorage

# Parameter Validation -----------------------------------------------------------------------------

def check(condition, message):
    """Validate a constructor parameter; raise :class:`ValueError` with ``message`` if false.

    Used instead of ``assert`` so validation survives ``python -O`` and gives users an
    actionable error instead of a bare ``AssertionError``.
    """
    if not condition:
        raise ValueError(message)

# Layouts ------------------------------------------------------------------------------------------

def real_layout(data_width=16, n_samples=1):
    """Stream payload layout for real signed samples (``n_samples`` lanes per beat if > 1)."""
    if n_samples == 1:
        return [("data", (data_width, True))]
    return [("data", n_samples*data_width)]

def real_lanes(endpoint, data_width, n_samples):
    """Per-lane ``data`` bit-slices of a multi-sample real endpoint (lane 0 = first sample)."""
    return [endpoint.data[k*data_width:(k + 1)*data_width] for k in range(n_samples)]

def iq_layout(data_width=16, n_samples=1):
    """Stream payload layout for complex signed I/Q samples (Q1.(N-1) by default).

    With ``n_samples > 1`` the layout carries that many I/Q pairs per beat (multi-sample-per-
    cycle datapaths for rates above the fabric clock): lanes are concatenated LSB-first in each
    field (lane 0 = first/oldest sample) and extracted with :func:`iq_lanes`.
    """
    if n_samples == 1:
        return [
            ("i", (data_width, True)),
            ("q", (data_width, True)),
        ]
    return [
        ("i", n_samples*data_width),
        ("q", n_samples*data_width),
    ]

def iq_symbol_layout(data_width=16, symbol_width=2):
    """Complex sample plus a hard-decision symbol (QPSK uses ``symbol_width=2``)."""
    return iq_layout(data_width) + [("symbol", symbol_width)]

# Timestamps (see litedsp/stream/timestamp.py and doc/timestamps.md).
TIMESTAMP_WIDTH = 64

def time_param_layout(width=TIMESTAMP_WIDTH):
    """Stream *param* layout for timestamped streams (rides next to the payload).

    ``timestamp`` is the :class:`~litedsp.stream.timestamp.LiteDSPTimeCore` count at the
    sample's ingress edge; ``stream_id`` identifies the tagging point in multi-stream designs.
    Params are per-frame constants in framed streams (tagged on ``first``), so plain blocks
    stay time-agnostic: strip them with :class:`~litedsp.stream.timestamp.LiteDSPTimeUntagger`
    (or ``connect(..., omit={"timestamp", "stream_id"})``) before entering a DSP chain.
    """
    return [
        ("timestamp", width),
        ("stream_id", 8),
    ]

def iq_lanes(endpoint, data_width, n_samples):
    """Per-lane ``(i, q)`` bit-slices of a multi-sample endpoint (lane 0 = first sample).

    Slices are raw bits: assign them to/from ``(data_width, True)`` Signals to reinterpret the
    sign before arithmetic.
    """
    return [(endpoint.i[k*data_width:(k + 1)*data_width],
             endpoint.q[k*data_width:(k + 1)*data_width]) for k in range(n_samples)]

# Fixed-Point Format -------------------------------------------------------------------------------

class Qmn:
    """Signed fixed-point format descriptor.

    Parameters
    ----------
    m : int
        Integer bits, **including** the sign bit.
    n : int
        Fractional bits.

    Example: ``Qmn(1, 15)`` is Q1.15 (16-bit, range [-1.0, +1.0)).
    """
    def __init__(self, m, n):
        check(m >= 1 and n >= 0, "expected m >= 1 and n >= 0")
        self.m     = m
        self.n     = n
        self.width = m + n

    @property
    def shape(self):
        """Migen signed shape tuple ``(width, True)``."""
        return (self.width, True)

    @property
    def scale(self):
        """Number of LSBs per integer unit (``2**n``)."""
        return 1 << self.n

    def to_float(self, x):
        """Convert a raw integer sample to float."""
        return x / self.scale

    def from_float(self, x):
        """Convert a float to a raw integer sample, clamped to the representable range."""
        v   = int(round(x * self.scale))
        lo  = -(1 << (self.width - 1))
        hi  =  (1 << (self.width - 1)) - 1
        return max(lo, min(hi, v))

    def __repr__(self):
        return f"Q{self.m}.{self.n}"

# Default sample format.
Q15 = Qmn(1, 15)

# Fixed-Point Helpers ------------------------------------------------------------------------------
#
# These return Migen expressions (use inside self.comb / self.sync). They mirror the NumPy
# reference helpers in test/models.py so simulation matches the golden model bit-for-bit.

def rounded(value, shift):
    """Arithmetic right-shift of signed ``value`` by ``shift`` bits, rounding half up.

    Equivalent to ``floor(value / 2**shift + 0.5)`` (round half toward +inf). With
    ``shift == 0`` it returns ``value`` unchanged.
    """
    if shift == 0:
        return value
    return (value + (1 << (shift - 1))) >> shift

def overflow(value, out_width):
    """Expression that is 1 when signed ``value`` does not fit in ``out_width`` bits.

    NOTE: deliberately no negative constants in comparisons. The LiteX Verilog backend emits a
    negative constant as ``-N'hX`` (unary minus on an *unsigned* literal); per Verilog rules the
    unsigned operand turns the whole comparison unsigned, inverting the result for positive
    values -- a sim/synth mismatch found on hardware (every positive sample saturated to the
    most-negative code). ``value + half < 0`` is equivalent and emits sign-safe Verilog.
    """
    hi   = (1 << (out_width - 1)) - 1
    half = 1 << (out_width - 1)
    return (value > hi) | ((value + half) < 0)

def saturated(value, out_width):
    """Clamp signed ``value`` to the signed ``out_width`` range (symmetric two's-complement).

    See :func:`overflow` for why the low-side compare is written as ``value + half < 0``.
    The low clamp *arm* stays the signed constant ``lo``: an unsigned bit-pattern constant
    would zero-extend (+2^(w-1)) when the result is used in wider arithmetic. Note that the
    backend emits the arm as ``-N'hX``, which is only sign-safe when the result is assigned to
    a signal of exactly ``out_width`` bits -- the recommended usage.
    """
    hi   = (1 << (out_width - 1)) - 1
    lo   = -(1 << (out_width - 1))
    half = 1 << (out_width - 1)
    return Mux(value > hi, hi, Mux((value + half) < 0, lo, value))

def scaled(value, shift, out_width):
    """Round ``value`` down by ``shift`` bits then saturate to ``out_width``.

    Returns ``(result, ovf)`` where ``result`` is the saturated rounded expression and
    ``ovf`` is a 1-bit overflow expression (set when rounding overflowed ``out_width``).
    """
    r = rounded(value, shift)
    return saturated(r, out_width), overflow(r, out_width)

# Bypass -------------------------------------------------------------------------------------------

def add_bypass(module, output_registered=True):
    """Add a runtime ``bypass`` control to a fixed-latency, layout-preserving block.

    When ``bypass`` is set, the sink payload passes to the source unmodified with the same
    latency as the processing path (a delay-matched shadow of the input is muxed onto the
    output). Call at the end of the hardware section, after the datapath: the override
    relies on Migen's ordered same-process assignments (later statements win).

    ``output_registered`` selects the override style to match how the block drives its
    source payload: ``True`` for sync-registered outputs (the override register is the last
    delay stage), ``False`` for comb-driven outputs (a full-latency delay chain + comb mux).

    Requires ``module.sink``/``module.source`` with identical payload layouts and an integer
    ``module.latency >= 1`` whose pipeline advances when the output can accept a sample.
    """
    check(getattr(module, "latency", None) and module.latency >= 1, "expected getattr(module, 'latency', None) and module.latency >= 1")
    module.bypass = Signal()  # Passthrough (skip processing).
    adv = Signal()
    module.comb += adv.eq(module.source.ready | ~module.source.valid)
    fields = [f[0] for f in module.sink.description.payload_layout]
    stages = module.latency - (1 if output_registered else 0)
    for name in fields:
        tap = getattr(module.sink, name)
        for _ in range(stages):  # Delay-match the processing pipeline.
            d = Signal.like(tap)
            module.sync += If(adv, d.eq(tap))
            tap = d
        if output_registered:
            module.sync += If(adv & module.bypass, getattr(module.source, name).eq(tap))
        else:
            module.comb += If(module.bypass, getattr(module.source, name).eq(tap))

def add_bypass_csr(module):
    """CSR for :func:`add_bypass` (call from ``add_csr``)."""
    module._bypass = CSRStorage(1, reset=0, name="bypass", description="Bypass block (passthrough).")
    module.comb += module.bypass.eq(module._bypass.storage)
