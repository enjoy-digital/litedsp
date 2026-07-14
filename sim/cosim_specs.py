#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Declarative Verilator co-simulation specs: one entry per cosim-eligible block.

``SPECS`` covers exactly the blocks marked ``cosim=True`` in ``test/registry.py`` (enforced by
:func:`check_coverage`, called by the runner). Each spec function returns
``(dut, cols, n_out, model)``:

- ``dut``   : the block, built with ``with_csr=False``; controls are set through reset values
              (``signal.reset = value``), so they need no top-level ports.
- ``cols``  : stimulus columns, one per sink payload field, sinks in discovery order
              (``litedsp.flow.metadata._ports``: sorted names, fields in layout order);
              empty for source-only blocks (NCO).
- ``n_out`` : number of output samples to capture (kept a few short of the steady-state total
              so the run terminates on an exact count).
- ``model`` : ``model(cols) -> [expected output columns]`` (bit-exact NumPy golden model from
              ``test/models.py``), one array (>= n_out long) per source payload field.
"""

import random

import numpy as np

from test import models

# Stimulus -----------------------------------------------------------------------------------------

def _rand_cols(n_cols, n, lo=-20000, hi=20000, seed=1):
    prng = random.Random(seed)
    return [[prng.randint(lo, hi) for _ in range(n)] for _ in range(n_cols)]

# Generation ---------------------------------------------------------------------------------------

def spec_nco():
    from litedsp.generation.nco import LiteDSPNCO
    n, phase_inc = 256, 0x01234567
    dut = LiteDSPNCO(data_width=16, with_csr=False)
    dut.phase_inc.reset = phase_inc
    return dut, [], n, lambda c: list(models.nco_model(phase_inc, n))

# Mixing -------------------------------------------------------------------------------------------

def spec_mixer():
    from litedsp.mixing.mixer import LiteDSPMixer
    n    = 300
    dut  = LiteDSPMixer(data_width=16, with_csr=False)             # mode reset = 0 (down).
    cols = _rand_cols(4, n)                                        # sink_a(i,q), sink_b(i,q).
    return dut, cols, n - 4, lambda c: list(models.mixer_model(c[0], c[1], c[2], c[3]))

# Filter -------------------------------------------------------------------------------------------

def spec_fir_real():
    from litedsp.filter.fir    import LiteDSPFIRFilter
    from litedsp.filter.design import firwin_lowpass
    n, n_taps = 200, 17
    coeffs = firwin_lowpass(n_taps, 0.2)
    dut = LiteDSPFIRFilter(n_taps=n_taps, data_width=16)
    for t, c in enumerate(coeffs):
        dut.coeffs[t].reset = int(c)
    cols = _rand_cols(1, n)
    return dut, cols, n - 8, lambda c: [models.fir_model(np.array(c[0]), coeffs)]

def spec_fir_complex():
    from litedsp.filter.fir    import LiteDSPFIRFilterComplex
    from litedsp.filter.design import firwin_lowpass
    n, n_taps = 200, 17
    coeffs = firwin_lowpass(n_taps, 0.2)
    dut  = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=16, coefficients=coeffs, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 8, lambda c: list(models.fir_complex_model(c[0], c[1], coeffs))

def spec_fir_decimator():
    from litedsp.filter.fir_poly import LiteDSPFIRDecimator
    from litedsp.filter.design   import firwin_lowpass
    n, n_taps, R = 256, 16, 8
    coeffs = firwin_lowpass(n_taps, 0.4/R)
    dut  = LiteDSPFIRDecimator(n_taps=n_taps, decimation=R, data_width=16,
        coefficients=coeffs, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n//R - 2, lambda c: [models.fir_decimator_model(c[0], coeffs, R),
                                           models.fir_decimator_model(c[1], coeffs, R)]

def spec_fir_interpolator():
    from litedsp.filter.fir_poly import LiteDSPFIRInterpolator
    from litedsp.filter.design   import firwin_lowpass
    n, n_taps, L = 48, 16, 8
    coeffs = firwin_lowpass(n_taps, 0.4/L, gain=L)                 # Gain L offsets zero-stuff loss.
    dut  = LiteDSPFIRInterpolator(n_taps=n_taps, interpolation=L, data_width=16,
        coefficients=coeffs, with_csr=False)
    cols = _rand_cols(2, n, lo=-8000, hi=8000)
    return dut, cols, n*L - 8, lambda c: [models.fir_interpolator_model(c[0], coeffs, L),
                                          models.fir_interpolator_model(c[1], coeffs, L)]

def spec_cic_decimator():
    from litedsp.filter.cic import LiteDSPCICDecimator
    n, R, N = 512, 8, 3
    dut  = LiteDSPCICDecimator(data_width=16, decimation=R, n_stages=N, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n//R - 4, lambda c: [models.cic_decimator_model(np.array(c[0]), R, N),
                                           models.cic_decimator_model(np.array(c[1]), R, N)]

def spec_cic_interpolator():
    from litedsp.filter.cic import LiteDSPCICInterpolator
    n, R, N = 64, 8, 3
    dut  = LiteDSPCICInterpolator(data_width=16, interpolation=R, n_stages=N, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n*R - 2*R, lambda c: [models.cic_interpolator_model(np.array(c[0]), R, N),
                                            models.cic_interpolator_model(np.array(c[1]), R, N)]

def spec_iir_biquad():
    from litedsp.filter.iir_biquad import LiteDSPIIRBiquad
    from litedsp.filter.design     import biquad_sos_quantize
    n  = 300
    w0, alpha, cw = 2*np.pi*0.1, np.sin(2*np.pi*0.1)/(2*0.707), np.cos(2*np.pi*0.1)
    sos = [(1 - cw)/2, 1 - cw, (1 - cw)/2, 1 + alpha, -2*cw, 1 - alpha]  # RBJ low-pass fc=0.1.
    secs, frac = biquad_sos_quantize([sos], frac_bits=14)
    dut  = LiteDSPIIRBiquad(data_width=16, coefficients=secs[0], frac_bits=frac, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.iir_biquad_model(c[0], secs[0], frac),
                                        models.iir_biquad_model(c[1], secs[0], frac)]

def spec_dc_blocker():
    from litedsp.filter.dc_blocker import LiteDSPDCBlocker
    n    = 300
    dut  = LiteDSPDCBlocker(data_width=16, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.dc_blocker_model(np.array(c[0])),
                                        models.dc_blocker_model(np.array(c[1]))]

def spec_moving_average():
    from litedsp.filter.moving_average import LiteDSPMovingAverage
    n, length_log2 = 300, 4
    dut  = LiteDSPMovingAverage(data_width=16, length_log2=length_log2, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.moving_average_model(np.array(c[0]), length_log2),
                                        models.moving_average_model(np.array(c[1]), length_log2)]

# Level --------------------------------------------------------------------------------------------

def spec_gain():
    from litedsp.level.gain import LiteDSPGain
    n, gain, shift = 300, 0x2C00, 1                                # 0.6875 in Q2.14, extra /2.
    dut = LiteDSPGain(data_width=16, with_csr=False)
    dut.gain.reset  = gain
    dut.shift.reset = shift
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: list(models.gain_model(c[0], c[1], gain, shift))

def spec_log2():
    from litedsp.level.logdb import LiteDSPLog2
    n    = 300
    dut  = LiteDSPLog2(in_width=32, frac_bits=8, with_csr=False)
    cols = _rand_cols(1, n, lo=0, hi=2**31 - 1)                    # Unsigned magnitude input.
    return dut, cols, n - 4, lambda c: [models.log2_model(np.array(c[0]))]

# Comm ---------------------------------------------------------------------------------------------

def spec_soft_demapper():
    from litedsp.comm.soft_demap import LiteDSPSoftDemapper
    n, bpa, spacing, scale = 300, 2, 6000, 24                      # 16-QAM, ~full LLR range.
    dut = LiteDSPSoftDemapper(bits_per_axis=bpa, spacing=spacing, llr_bits=4, data_width=16,
        with_csr=False)
    dut.llr_scale.reset = scale
    cols = _rand_cols(2, n, lo=-32768, hi=32767)
    return dut, cols, n - 4, lambda c: [models.soft_demap_model(c[0], c[1], bits_per_axis=bpa,
        spacing=spacing, llr_bits=4, llr_scale=scale)]

# Correction ---------------------------------------------------------------------------------------

def spec_dc_offset():
    from litedsp.correction.dc_offset import LiteDSPDCOffset
    n, mu = 300, 10
    dut  = LiteDSPDCOffset(data_width=16, mu=mu, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.dc_offset_model(c[0], mu),
                                        models.dc_offset_model(c[1], mu)]

# Analysis -----------------------------------------------------------------------------------------

def spec_magnitude():
    from litedsp.analysis.magnitude import LiteDSPMagnitude
    n    = 300
    dut  = LiteDSPMagnitude(data_width=16, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.magnitude_model(np.array(c[0]), np.array(c[1]))]

def spec_window():
    # Window *sinks* a plain stream (the frame counter is internal); it only *produces*
    # first/last frame markers, which the generic TB ignores. Blocks that would need
    # first/last driven on their sink (framed-stream input) are not in the cosim set yet;
    # TODO: extend stream_tb.cpp with first/last columns when one lands.
    from litedsp.analysis.window import LiteDSPWindow, window_coefficients
    n, n_win = 192, 64
    dut    = LiteDSPWindow(n=n_win, data_width=16, window="hann", with_csr=False)
    coeffs = window_coefficients(n_win, "hann")
    cols   = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: list(models.window_model(c[0], c[1], coeffs))

# Table --------------------------------------------------------------------------------------------

SPECS = {
    "nco":              spec_nco,
    "mixer":            spec_mixer,
    "fir_real":         spec_fir_real,
    "fir_complex":      spec_fir_complex,
    "fir_decimator":    spec_fir_decimator,
    "fir_interpolator": spec_fir_interpolator,
    "cic_decimator":    spec_cic_decimator,
    "cic_interpolator": spec_cic_interpolator,
    "iir_biquad":       spec_iir_biquad,
    "dc_blocker":       spec_dc_blocker,
    "moving_average":   spec_moving_average,
    "gain":             spec_gain,
    "log2":             spec_log2,
    "soft_demapper":    spec_soft_demapper,
    "dc_offset":        spec_dc_offset,
    "magnitude":        spec_magnitude,
    "window":           spec_window,
}

# Known failures -----------------------------------------------------------------------------------
#
# Real RTL divergence *found by this co-simulation*, kept visible as XFAIL rather than papered
# over (the golden models and the migen simulation are correct; the emitted Verilog is not):
# Migen prints ``sink.i * gain`` inline, and Verilog sizes ``*`` to max(operand widths) in a
# 16-bit assignment/comparison context, so the synthesized product is truncated to 16 bits
# (migen semantics — and hence the migen-sim-based unit tests — use the full 32). Blocks that
# register the product into an explicitly sized Signal first (fir, mixer, iir_biquad) are
# immune. The fix belongs in litedsp/level/gain.py and litedsp/analysis/window.py (route the
# product through a full-width intermediate Signal before ``scaled()``); it is gateware-
# behavior-changing and therefore out of scope for the co-sim harness.
KNOWN_FAIL = {}

# Coverage ratchet ---------------------------------------------------------------------------------

def check_coverage():
    """SPECS must cover exactly the ``cosim=True`` blocks of ``test/registry.py`` VSPEC."""
    from test.registry import VSPEC
    eligible = {k for k, v in VSPEC.items() if v["cosim"]}
    missing  = eligible - set(SPECS)
    extra    = set(SPECS) - eligible
    if missing or extra:
        raise RuntimeError(f"cosim spec/VSPEC mismatch: missing={sorted(missing)} extra={sorted(extra)}")
