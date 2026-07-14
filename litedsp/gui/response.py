#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Quantized frequency-response preview for filter nodes (pure / testable, no DearPyGui).

:func:`response_for` maps a registry key + current node params to ``(freqs, H_db)`` — or None
for blocks without a meaningful magnitude response. Tap-based filters are evaluated from their
*quantized* integer coefficients (the same :mod:`litedsp.filter.design` calls the blocks make),
so the plot shows fixed-point truth (finite stopband floor included), not the ideal float design.
Frequencies are normalized to the rate the filter arithmetic runs at (0..0.5).
"""

import numpy as np

from litedsp.filter import design

DB_FLOOR = -160.0

# Evaluation helpers -------------------------------------------------------------------------------

def _fir_db(taps, freqs, data_width):
    """(freqs, H_db) of integer Q1.(N-1) ``taps``, via design.freq_response when available."""
    fr = getattr(design, "freq_response", None)   # Landed from the design workstream; prefer it.
    if fr is not None:
        f, h_db = fr(taps, n_points=len(freqs), data_width=data_width)
        return np.asarray(f, dtype=float), np.asarray(h_db, dtype=float)
    k = np.arange(len(taps))
    h = np.exp(-2j*np.pi*np.outer(freqs, k)) @ np.asarray(taps, dtype=float)
    return freqs, _db(np.abs(h)/(1 << (data_width - 1)))

def _rational(num, den, freqs):
    """|H| of an IIR ``H(z) = num(z^-1)/den(z^-1)`` with integer/float coefficient lists."""
    z = np.exp(-2j*np.pi*freqs)
    n = sum(c*z**k for k, c in enumerate(num))
    d = sum(c*z**k for k, c in enumerate(den))
    return np.abs(n)/np.abs(d)

def _cic_mag(freqs, R, N, M=1):
    """Closed-form CIC magnitude ``|sin(pi f R M)/(R M sin(pi f))|^N`` (unity at DC)."""
    with np.errstate(divide="ignore", invalid="ignore"):
        mag = np.abs(np.sin(np.pi*freqs*R*M)/(R*M*np.sin(np.pi*freqs)))**N
    mag[freqs == 0] = 1.0
    return mag

def _db(mag):
    return 20*np.log10(np.maximum(np.asarray(mag, dtype=float), 10**(DB_FLOOR/20)))

def _int_taps(coeffs, data_width):
    """Coefficients as quantized integers (floats are quantized to Q1.(N-1) like the blocks)."""
    if all(isinstance(c, (int, np.integer)) for c in coeffs):
        return list(coeffs)
    return design.quantize(coeffs, data_width - 1, data_width)

# Per-block responses ------------------------------------------------------------------------------

def response_for(key, params=None, data_width=16, n_points=512):
    """``(freqs, H_db)`` for a filter block at its current params, or None otherwise.

    ``params`` uses the block's constructor names (missing entries fall back to the block's
    construction defaults; FIR decimator/interpolator previews default to the matching
    anti-alias/anti-image firwin design at their rate-change config).
    """
    p     = dict(params or {})
    dw    = int(p.get("data_width", data_width))
    freqs = np.linspace(0, 0.5, n_points)
    scale = 1 << (dw - 1)                                   # Q1.(N-1) unity.

    def fir_db(taps):
        return _fir_db(taps, freqs, dw)

    if key in ("fir_real", "fir_complex"):
        n_taps = int(p.get("n_taps", 32))
        coeffs = p.get("coefficients") or [scale - 1] + [0]*(n_taps - 1)  # Block default: impulse.
        return fir_db(_int_taps(coeffs, dw))

    if key == "fir_decimator":
        n_taps, R = int(p.get("n_taps", 32)), int(p.get("decimation", 8))
        coeffs = p.get("coefficients") or design.firwin_lowpass(n_taps, 0.5/R, data_width=dw)
        return fir_db(_int_taps(coeffs, dw))

    if key == "fir_interpolator":
        n_taps, L = int(p.get("n_taps", 32)), int(p.get("interpolation", 8))
        coeffs = p.get("coefficients") or design.firwin_lowpass(n_taps, 0.5/L, data_width=dw, gain=L)
        return fir_db(_int_taps(coeffs, dw))

    if key in ("halfband_dec", "halfband_int"):
        n_taps = int(p.get("n_taps", 23))
        gain   = 2.0 if key == "halfband_int" else 1.0      # x2 compensates interpolation loss.
        return fir_db(design.halfband_coefficients(n_taps, data_width=dw, gain=gain))

    if key == "hilbert":
        return fir_db(design.hilbert_coefficients(int(p.get("n_taps", 23)), data_width=dw))

    if key == "pulse_shaper":
        sps, span = int(p.get("sps", 4)), int(p.get("span", 8))
        beta      = float(p.get("beta", 0.35))
        return fir_db(design.rrc_coefficients(sps, span, beta, data_width=dw, gain=sps))

    if key in ("cic_decimator", "cic_interpolator"):
        R = int(p.get("decimation" if key == "cic_decimator" else "interpolation", 8))
        N = int(p.get("n_stages", 3))
        M = int(p.get("diff_delay", 1))
        return freqs, _db(_cic_mag(freqs, R, N, M))

    if key == "moving_average":
        L = 1 << int(p.get("length_log2", 4))
        return freqs, _db(_cic_mag(freqs, L, 1))            # Boxcar = single-stage CIC shape.

    if key == "dc_blocker":
        a = 1.0 - 2.0**-int(p.get("pole_shift", 5))         # y = x - x1 + a*y1.
        return freqs, _db(_rational([1, -1], [1, -a], freqs))

    if key == "iir_biquad":
        frac = int(p.get("frac_bits", 14))
        c = p.get("coefficients") or {"b0": 1 << frac, "b1": 0, "b2": 0, "a1": 0, "a2": 0}
        return freqs, _db(_rational([c["b0"], c["b1"], c["b2"]],
                                    [1 << frac, c["a1"], c["a2"]], freqs))

    if key == "notch":
        frac = int(p.get("frac", 14))
        r    = float(p.get("r", 0.96))
        cq   = int(round(float(p.get("cos_w0", 0.0))*(1 << frac)))  # CSR reset 0 -> f0 = 0.25.
        gq   = int(round(((1 + r*r)/2)*(1 << frac)))
        rq   = int(round(r*(1 << frac)))
        r2q  = int(round(r*r*(1 << frac)))
        b1   = -((gq*2*cq) >> frac)                                 # Same >>frac truncation as RTL.
        a1   = (rq*2*cq) >> frac
        return freqs, _db(_rational([gq, b1, gq], [1 << frac, -a1, r2q], freqs))

    if key == "allpass":
        frac = int(p.get("frac", 14))
        aq   = int(round(float(p.get("a", 0.5))*(1 << frac)))
        return freqs, _db(_rational([-aq, 1 << frac], [1 << frac, -aq], freqs))

    if key == "comb_filter":
        D = int(p.get("depth", 8))
        return freqs, _db(_rational([1] + [0]*(D - 1) + [-1], [1], freqs))

    return None
