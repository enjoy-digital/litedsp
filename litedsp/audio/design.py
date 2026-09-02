#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side design math for the audio blocks (NumPy only, not re-exported).

Biquad designs return float rows ``[b0, b1, b2, a0, a1, a2]`` for
:func:`litedsp.filter.design.biquad_sos_quantize`; frequencies are normalized to the sample
rate (``f0 = f_hz/fs``, 0..0.5) unless a ``sample_rate`` is given.
"""

import math

import numpy as np

# Biquads (Audio EQ Cookbook, R. Bristow-Johnson) -------------------------------------------------

RBJ_KINDS = ("lowpass", "highpass", "bandpass", "notch", "allpass", "peaking", "lowshelf", "highshelf")

def rbj_biquad(kind, f0, gain_db=0.0, q=1/math.sqrt(2), slope=None, sample_rate=None):
    """One RBJ cookbook section: ``kind`` in ``RBJ_KINDS``, center/corner ``f0`` (normalized, or
    Hz with ``sample_rate``), ``gain_db`` (peaking/shelves), ``q`` (or a shelf ``slope``)."""
    if kind not in RBJ_KINDS:
        raise ValueError(f"expected kind in {RBJ_KINDS}")
    if sample_rate is not None:
        f0 = f0/sample_rate
    if not 0 < f0 < 0.5:
        raise ValueError("expected 0 < f0 < 0.5 (normalized to the sample rate)")
    A  = 10**(gain_db/40)
    w0 = 2*math.pi*f0
    cw, sw = math.cos(w0), math.sin(w0)
    if kind in ("lowshelf", "highshelf") and slope is not None:
        alpha = sw/2*math.sqrt((A + 1/A)*(1/slope - 1) + 2)
    else:
        alpha = sw/(2*q)
    if kind == "lowpass":
        return [(1 - cw)/2, 1 - cw, (1 - cw)/2, 1 + alpha, -2*cw, 1 - alpha]
    if kind == "highpass":
        return [(1 + cw)/2, -(1 + cw), (1 + cw)/2, 1 + alpha, -2*cw, 1 - alpha]
    if kind == "bandpass":                                   # Constant 0 dB peak gain.
        return [alpha, 0.0, -alpha, 1 + alpha, -2*cw, 1 - alpha]
    if kind == "notch":
        return [1.0, -2*cw, 1.0, 1 + alpha, -2*cw, 1 - alpha]
    if kind == "allpass":
        return [1 - alpha, -2*cw, 1 + alpha, 1 + alpha, -2*cw, 1 - alpha]
    if kind == "peaking":
        return [1 + alpha*A, -2*cw, 1 - alpha*A, 1 + alpha/A, -2*cw, 1 - alpha/A]
    sa = 2*math.sqrt(A)*alpha
    if kind == "lowshelf":
        return [A*((A + 1) - (A - 1)*cw + sa), 2*A*((A - 1) - (A + 1)*cw), A*((A + 1) - (A - 1)*cw - sa),
                (A + 1) + (A - 1)*cw + sa, -2*((A - 1) + (A + 1)*cw), (A + 1) + (A - 1)*cw - sa]
    return [A*((A + 1) + (A - 1)*cw + sa), -2*A*((A - 1) + (A + 1)*cw), A*((A + 1) + (A - 1)*cw - sa),
            (A + 1) - (A - 1)*cw + sa, 2*((A - 1) - (A + 1)*cw), (A + 1) - (A - 1)*cw - sa]

def linkwitz_riley_sos(f_cutoff, btype="lowpass", order=4, sample_rate=None):
    """Linkwitz-Riley crossover section set: ``order`` 4 (two cascaded Butterworth biquads, the
    LP + HP sum is allpass-flat) or 2 (one section, Q = 0.5)."""
    if order not in (2, 4):
        raise ValueError("expected order in (2, 4)")
    if order == 2:
        return [rbj_biquad(btype, f_cutoff, q=0.5, sample_rate=sample_rate)]
    q = 1/math.sqrt(2)
    return [rbj_biquad(btype, f_cutoff, q=q, sample_rate=sample_rate) for _ in range(2)]

def k_weighting_sos(sample_rate=48000):
    """ITU-R BS.1770 K-weighting: high shelf (+4 dB above ~1.7 kHz) + RLB high-pass (38 Hz),
    designed for any sample rate from the standard's 48 kHz prototype parameters."""
    shelf = rbj_biquad("highshelf", 1681.974450955533, gain_db=3.999843853973347, q=0.7071752369554196,
        sample_rate=sample_rate)
    hp    = rbj_biquad("highpass", 38.13547087602444, q=0.5003270373238773, sample_rate=sample_rate)
    return [shelf, hp]

# Levels and time constants -------------------------------------------------------------------------

def db_to_linear(db):
    return 10**(np.asarray(db, float)/20)

def linear_to_db(x):
    return 20*np.log10(np.maximum(np.abs(np.asarray(x, float)), 1e-30))

def log2_from_db(db, frac_bits=8):
    """dB -> the compressor's log2 domain (Q.frac_bits): ``round(db/6.0206 * 2**frac_bits)``."""
    return int(round(db/(20*math.log10(2))*(1 << frac_bits)))

def time_constant_coeff(ms, sample_rate=48000, frac_bits=16):
    """One-pole smoother coefficient (Q0.frac_bits) for a 63 % time of ``ms`` milliseconds:
    ``alpha = 1 - exp(-1/(ms*1e-3*fs))``; 0 ms -> 1.0 (instantaneous)."""
    if ms <= 0:
        return (1 << frac_bits) - 1
    return int(round((1 - math.exp(-1/(ms*1e-3*sample_rate)))*(1 << frac_bits)))

def pan_matrix(position):
    """Constant-power pan of a mono source into (L, R): position -1 (left) .. +1 (right).
    Returns the stereo-matrix coefficients ``(a, b, c, d)`` for an input carried on L."""
    theta = (position + 1)/2*math.pi/2
    return (math.cos(theta), 0.0, math.sin(theta), 0.0)

def ms_matrix(encode=True):
    """Stereo-matrix coefficients for mid/side encoding (``M = (L+R)/2, S = (L-R)/2``) or
    decoding (``L = M+S, R = M-S``)."""
    return (0.5, 0.5, 0.5, -0.5) if encode else (1.0, 1.0, 1.0, -1.0)
