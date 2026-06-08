#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""NumPy golden reference models for LiteDSP blocks.

Each model reproduces the bit-level behavior of the corresponding gateware (same fixed-point
rounding/saturation, same accumulation order) so tests can compare simulation output against
it either bit-exactly (structural blocks) or above an SNR threshold (arithmetic blocks).
"""

import numpy as np

from test.common import np_rounded, np_saturated, np_scaled

# NCO ----------------------------------------------------------------------------------------------

def nco_lut(lut_depth, data_width):
    """Return the (cos, sin) lookup tables used by the NCO, as signed integer arrays."""
    scale = (1 << (data_width - 1)) - 1
    k     = np.arange(lut_depth)
    cos_t = np.round(np.cos(2*np.pi*k/lut_depth)*scale).astype(np.int64)
    sin_t = np.round(np.sin(2*np.pi*k/lut_depth)*scale).astype(np.int64)
    return cos_t, sin_t

def nco_model(phase_inc, n, phase_bits=32, data_width=16, lut_depth=1024):
    """Reference for litedsp.generation.nco.NCO. Returns (i, q) integer arrays of length n."""
    addr_bits    = int(round(np.log2(lut_depth)))
    cos_t, sin_t = nco_lut(lut_depth, data_width)
    mask         = (1 << phase_bits) - 1
    phase        = 0
    out_i, out_q = [], []
    for _ in range(n):
        phase = (phase + phase_inc) & mask
        addr  = phase >> (phase_bits - addr_bits)
        out_i.append(cos_t[addr])
        out_q.append(sin_t[addr])
    return np.array(out_i), np.array(out_q)

# Mixer --------------------------------------------------------------------------------------------

def mixer_model(a_i, a_q, b_i, b_q, mode="down", data_width=16, shift=None):
    """Reference for litedsp.mixing.mixer.Mixer (complex multiply + round/saturate)."""
    if shift is None:
        shift = data_width - 1
    a_i, a_q = np.asarray(a_i, np.int64), np.asarray(a_q, np.int64)
    b_i, b_q = np.asarray(b_i, np.int64), np.asarray(b_q, np.int64)
    if mode == "down":  # (a) * conj(b)
        i_full = a_i*b_i + a_q*b_q
        q_full = a_q*b_i - a_i*b_q
    else:               # (a) * (b)
        i_full = a_i*b_i - a_q*b_q
        q_full = a_q*b_i + a_i*b_q
    return np_scaled(i_full, shift, data_width), np_scaled(q_full, shift, data_width)

# FIR ----------------------------------------------------------------------------------------------

def fir_model(x, coeffs, data_width=16, shift=None):
    """Reference for a single real FIR (litedsp.filter.fir.FIRFilter)."""
    if shift is None:
        shift = data_width - 1
    x      = np.asarray(x, np.int64)
    coeffs = np.asarray(coeffs, np.int64)
    acc    = np.convolve(x, coeffs)[:len(x)]
    return np_scaled(acc, shift, data_width)

def fir_complex_model(i, q, coeffs, data_width=16, shift=None):
    """Reference for litedsp.filter.fir.FIRFilterComplex (same taps on I and Q)."""
    return fir_model(i, coeffs, data_width, shift), fir_model(q, coeffs, data_width, shift)

# Gain ---------------------------------------------------------------------------------------------

def gain_model(i, q, gain_factor, shift, data_width=16, gain_frac=None):
    """Reference for litedsp.level.gain.Gain (Q2.(N-2) mantissa + post-shift, round/saturate)."""
    if gain_frac is None:
        gain_frac = data_width - 2          # Q2.14 mantissa for 16-bit.
    total = gain_frac + shift
    i, q  = np.asarray(i, np.int64), np.asarray(q, np.int64)
    return (np_scaled(i*gain_factor, total, data_width),
            np_scaled(q*gain_factor, total, data_width))

# Power --------------------------------------------------------------------------------------------

def power_model(i, q, window=1):
    """Reference for litedsp.level.power.Power: block-averaged |x|^2 over `window` samples.

    Returns one averaged value per completed window (integer division, matching the HW
    accumulate-then-shift/divide behavior).
    """
    i, q = np.asarray(i, np.int64), np.asarray(q, np.int64)
    p    = i*i + q*q
    n    = (len(p)//window)*window
    if n == 0:
        return np.array([], dtype=np.int64)
    blocks = p[:n].reshape(-1, window)
    return blocks.sum(axis=1)//window

# CIC ----------------------------------------------------------------------------------------------

def _cic_growth(R, N, M):
    return int(np.ceil(N*np.log2(R*M)))

def _wrapper(W):
    mask = (1 << W) - 1
    half = 1 << (W - 1)
    def wrap(v):
        v &= mask
        return v - (1 << W) if v >= half else v
    return wrap

def cic_decimator_model(x, R, N=3, M=1, data_width=16):
    """Cycle-accurate reference for litedsp.filter.cic.CICDecimator (one channel)."""
    growth = _cic_growth(R, N, M)
    wrap   = _wrapper(data_width + growth)
    integ  = [0]*N
    combq  = [[0]*M for _ in range(N)]
    out, decim = [], 0
    for xn in np.asarray(x, np.int64):
        prev = int(xn)
        for k in range(N):
            integ[k] = wrap(integ[k] + prev)
            prev     = integ[k]
        if decim == R - 1:
            decim = 0
            c = integ[N - 1]
            for k in range(N):
                d = wrap(c - combq[k][M - 1])
                combq[k] = [c] + combq[k][:M - 1]
                c = d
            out.append(np_scaled(np.int64(c), growth, data_width))
        else:
            decim += 1
    return np.array(out, np.int64)

def cic_interpolator_model(x, R, N=3, M=1, data_width=16):
    """Cycle-accurate reference for litedsp.filter.cic.CICInterpolator (one channel)."""
    growth = int(np.ceil(N*np.log2(R*M) - np.log2(R)))
    wrap   = _wrapper(data_width + _cic_growth(R, N, M))
    combq  = [[0]*M for _ in range(N)]
    integ  = [0]*N
    out = []
    for xn in np.asarray(x, np.int64):
        # Comb cascade (input rate).
        c = int(xn)
        for k in range(N):
            d = wrap(c - combq[k][M - 1])
            combq[k] = [c] + combq[k][:M - 1]
            c = d
        # Zero-stuff by R into the integrators (output rate).
        for r in range(R):
            stuff = c if r == 0 else 0
            prev  = stuff
            for k in range(N):
                integ[k] = wrap(integ[k] + prev)
                prev     = integ[k]
            out.append(np_scaled(np.int64(integ[N - 1]), growth, data_width))
    return np.array(out, np.int64)

# Polyphase FIR ------------------------------------------------------------------------------------

def fir_decimator_model(x, coeffs, R, data_width=16, shift=None):
    """Reference for litedsp.filter.fir_poly.FIRDecimator (one channel)."""
    if shift is None:
        shift = data_width - 1
    conv = np.convolve(np.asarray(x, np.int64), np.asarray(coeffs, np.int64))[:len(x)]
    return np_scaled(conv[R - 1::R], shift, data_width)

def fir_interpolator_model(x, coeffs, L, data_width=16, shift=None):
    """Reference for litedsp.filter.fir_poly.FIRInterpolator (one channel)."""
    if shift is None:
        shift = data_width - 1
    up        = np.zeros(len(x)*L, np.int64)
    up[::L]   = np.asarray(x, np.int64)
    conv      = np.convolve(up, np.asarray(coeffs, np.int64))[:len(up)]
    return np_scaled(conv, shift, data_width)

# IIR Biquad ---------------------------------------------------------------------------------------

def iir_biquad_model(x, coeffs, frac_bits=14, data_width=16):
    """Reference for one litedsp.filter.iir_biquad.IIRBiquad section (one channel)."""
    SW = data_width + frac_bits + 4
    b0, b1, b2 = coeffs["b0"], coeffs["b1"], coeffs["b2"]
    a1, a2     = coeffs["a1"], coeffs["a2"]
    s1 = s2 = 0
    out = np.zeros(len(x), np.int64)
    for n, xn in enumerate(np.asarray(x, np.int64)):
        xn = int(xn)
        y  = int(np_scaled(np.int64(b0*xn + s1), frac_bits, data_width))
        s1 = int(np_saturated(np.int64(b1*xn + s2 - a1*y), SW))
        s2 = int(np_saturated(np.int64(b2*xn - a2*y), SW))
        out[n] = y
    return out

def iir_cascade_model(x, sections, frac_bits=14, data_width=16):
    """Reference for litedsp.filter.iir_biquad.IIRBiquadCascade (one channel)."""
    y = np.asarray(x, np.int64)
    for sec in sections:
        y = iir_biquad_model(y, sec, frac_bits, data_width)
    return y

# DC Blocker ---------------------------------------------------------------------------------------

def dc_blocker_model(x, pole_shift=5, data_width=16):
    """Reference for litedsp.filter.dc_blocker.DCBlocker (one channel)."""
    x = np.asarray(x, np.int64)
    y = np.zeros(len(x), np.int64)
    x_prev = 0
    y_prev = 0
    for n in range(len(x)):
        yv = np_saturated(x[n] - x_prev + y_prev - (y_prev >> pole_shift), data_width)
        y[n]   = yv
        x_prev = x[n]
        y_prev = yv
    return y

# Moving Average -----------------------------------------------------------------------------------

def moving_average_model(x, length_log2=4):
    """Reference for litedsp.filter.moving_average.MovingAverage (one channel)."""
    x   = np.asarray(x, np.int64)
    L   = 1 << length_log2
    acc = 0
    out = np.zeros(len(x), np.int64)
    for n in range(len(x)):
        old    = x[n - L] if n >= L else 0
        acc    = acc + x[n] - old
        out[n] = np_rounded(np.int64(acc), length_log2)
    return out

# ISqrt --------------------------------------------------------------------------------------------

def isqrt_model(x):
    """Reference for litedsp.numeric.ISqrt (floor integer square root)."""
    return np.array([int(np.floor(np.sqrt(int(v)))) for v in np.asarray(x, np.int64)], np.int64)

# Log2 ---------------------------------------------------------------------------------------------

def log2_model(x, in_width=32, frac_bits=8):
    """Reference for litedsp.level.logdb.Log2 (linear-mantissa approximation)."""
    out = []
    for v in np.asarray(x, np.int64):
        v = int(v)
        if v <= 0:
            out.append(0)
            continue
        msb     = v.bit_length() - 1
        shifted = v << (in_width - 1 - msb)
        mant    = (shifted >> (in_width - 1 - frac_bits)) & ((1 << frac_bits) - 1)
        out.append((msb << frac_bits) | mant)
    return np.array(out, np.int64)

# DC Offset Correction -----------------------------------------------------------------------------

def dc_offset_model(x, mu=10, data_width=16):
    """Reference for litedsp.correction.dc_offset.DCOffset (one channel)."""
    mean = 0
    out  = np.zeros(len(x), np.int64)
    for n, v in enumerate(np.asarray(x, np.int64)):
        v   = int(v)
        est = mean >> mu
        out[n] = int(np_saturated(np.int64(v - est), data_width))
        mean   = mean + (v - est)
    return out

# Magnitude ----------------------------------------------------------------------------------------

def magnitude_model(i, q, beta_shift=2):
    """Reference for litedsp.analysis.magnitude.Magnitude (alpha-max-beta-min)."""
    ai = np.abs(np.asarray(i, np.int64))
    aq = np.abs(np.asarray(q, np.int64))
    hi = np.maximum(ai, aq)
    lo = np.minimum(ai, aq)
    return hi + (lo >> beta_shift)

# Combine ------------------------------------------------------------------------------------------

def combine_model(channels_i, channels_q, enable=None, out_width=16):
    """Reference for litedsp.stream.combine.Combine (saturating sum of enabled channels)."""
    channels_i = np.asarray(channels_i, np.int64)   # shape (n_channels, n_samples)
    channels_q = np.asarray(channels_q, np.int64)
    n_channels = channels_i.shape[0]
    if enable is None:
        enable = np.ones(n_channels, dtype=np.int64)
    enable = np.asarray(enable, np.int64).reshape(-1, 1)
    sum_i  = (channels_i*enable).sum(axis=0)
    sum_q  = (channels_q*enable).sum(axis=0)
    return np_saturated(sum_i, out_width), np_saturated(sum_q, out_width)

# FFT ----------------------------------------------------------------------------------------------

def fft_model(frame_i, frame_q, data_width=16):
    """Reference for litedsp.analysis.fft.FFT: 1/N-scaled DFT, in natural (not bit-rev) order."""
    x = np.asarray(frame_i, float) + 1j*np.asarray(frame_q, float)
    return np.fft.fft(x)/len(x)

# Window -------------------------------------------------------------------------------------------

def window_model(i, q, coeffs, data_width=16):
    """Reference for litedsp.analysis.window.Window (per-frame coeff multiply + round/saturate)."""
    i, q   = np.asarray(i, np.int64), np.asarray(q, np.int64)
    n      = len(coeffs)
    w      = np.array([coeffs[k % n] for k in range(len(i))], dtype=np.int64)
    shift  = data_width - 1
    return np_scaled(i*w, shift, data_width), np_scaled(q*w, shift, data_width)

# Dropper (naive rate change) ----------------------------------------------------------------------

def decimate_model(x, factor):
    """Naive decimation (keep every `factor`-th sample), no anti-alias filtering."""
    return np.asarray(x)[::factor]

def interpolate_model(x, factor, mode="repeat"):
    """Naive interpolation by `factor` (zero-stuff or sample-and-hold)."""
    x = np.asarray(x, np.int64)
    if mode == "zero":
        out = np.zeros(len(x)*factor, dtype=np.int64)
        out[::factor] = x
        return out
    return np.repeat(x, factor)
