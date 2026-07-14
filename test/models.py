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

import math

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

# Clipper ------------------------------------------------------------------------------------------

def clipper_model(i, q, threshold, data_width=16):
    """Reference for litedsp.level.clipper.LiteDSPClipper (clamp I/Q to [-threshold, +threshold])."""
    i, q = np.asarray(i, np.int64), np.asarray(q, np.int64)
    return np.clip(i, -threshold, threshold), np.clip(q, -threshold, threshold)

# Squelch ------------------------------------------------------------------------------------------

def squelch_model(i, q, open_threshold, close_threshold):
    """Reference for litedsp.level.squelch.LiteDSPSquelch (hysteresis power gate).

    Power is the instantaneous ``i*i + q*q``; the gate opens at power >= open_threshold and
    closes at power < close_threshold. The gate state applied to sample n is the state after
    samples 0..n-1 (the HW output mux reads the pre-update gate register), so sample n's own
    power affects sample n+1 onward.
    """
    i, q  = np.asarray(i, np.int64), np.asarray(q, np.int64)
    out_i = np.zeros(len(i), np.int64)
    out_q = np.zeros(len(i), np.int64)
    gate  = 0
    for n in range(len(i)):
        if gate:
            out_i[n] = i[n]
            out_q[n] = q[n]
        p = int(i[n])*int(i[n]) + int(q[n])*int(q[n])
        if p >= open_threshold:
            gate = 1
        elif p < close_threshold:
            gate = 0
    return out_i, out_q

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

# PFB Channelizer ----------------------------------------------------------------------------------

def pfb_channelizer_model(i, q, coefficients, n_channels, data_width=16):
    """Bit-exact reference for litedsp.mixing.pfb_channelizer.LiteDSPPFBChannelizer.

    Critically-sampled uniform DFT filter bank. Per M-input frame m (newest sample index
    ``base = m*M + M - 1``): M polyphase branch dot-products (branch p = prototype phase
    ``coefficients[p::M]`` over samples ``x[base - p - t*M]``, zero history before the
    stream), then an M-point DFT with the gateware's quantized Q1.(W-1) twiddles
    (kernel ``exp(+2j*pi*k*p/M)``: channel k centered at ``+k/M`` of the input rate).
    Products/accumulations are exact; a single round-half-up + saturate by
    ``2*(data_width - 1)`` bits (coefficient + twiddle fractional bits) at the output.
    Returns ``(i, q)`` int arrays of ``(len(i)//M)*M`` samples (frame-major, channel =
    position within the frame).
    """
    M     = n_channels
    T     = len(coefficients)//M
    xi    = np.asarray(i, np.int64)
    xq    = np.asarray(q, np.int64)
    h     = np.asarray(coefficients, np.int64)
    scale = (1 << (data_width - 1)) - 1
    tw_c  = np.array([int(round(math.cos(2*math.pi*j/M)*scale)) for j in range(M)], np.int64)
    tw_s  = np.array([int(round(math.sin(2*math.pi*j/M)*scale)) for j in range(M)], np.int64)
    shift = 2*(data_width - 1)
    out_i, out_q = [], []
    for m in range(len(xi)//M):
        base = m*M + M - 1
        ui   = np.zeros(M, np.int64)  # Branch dot-products (full width, exact).
        uq   = np.zeros(M, np.int64)
        for p in range(M):
            for t in range(T):
                n = base - p - t*M
                if n >= 0:
                    ui[p] += h[p + t*M]*xi[n]
                    uq[p] += h[p + t*M]*xq[n]
        for k in range(M):
            j  = (k*np.arange(M)) % M     # Twiddle index k*p mod M.
            c, s = tw_c[j], tw_s[j]
            out_i.append(int(np_scaled(np.sum(ui*c) - np.sum(uq*s), shift, data_width)))
            out_q.append(int(np_scaled(np.sum(ui*s) + np.sum(uq*c), shift, data_width)))
    return np.array(out_i, np.int64), np.array(out_q, np.int64)

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

# LMS Equalizer ------------------------------------------------------------------------------------

def equalizer_model(i, q, d_i=None, d_q=None, n_taps=7, data_width=16, wfrac=14, wint=4,
    mu_shift=20, cma_egain=0, mode=0, cma_r2=0, dd_level=0, train=1):
    """Reference for litedsp.filter.equalizer.LiteDSPLMSEqualizer (bit-exact, all modes).

    Per accepted sample (the gateware gates everything on xfer, so the sequence is
    handshake-invariant): shift the input window, filter with the current weights, form the
    mode-selected error (0 = trained ``e = d - y``, 1 = CMA ``e = y*(R2 - |y|^2)`` with the
    gateware's frac-(W-1-cma_egain) rescale/round/saturate, 2 = DD nearest-QPSK at ``dd_level``), then
    apply the *previous* sample's error on its window snapshot (delayed LMS), gated by
    ``train``. ``mode`` and ``train`` accept scalars or per-sample sequences (runtime
    switching). Returns (i, q) output arrays.
    """
    W  = data_width
    F  = W - 1                                          # Sample fractional bits (Q1.F).
    ww = wint + wfrac                                   # Weight register width.
    n  = len(i)
    i, q  = np.asarray(i, np.int64), np.asarray(q, np.int64)
    d_i   = np.zeros(n, np.int64) if d_i is None else np.asarray(d_i, np.int64)
    d_q   = np.zeros(n, np.int64) if d_q is None else np.asarray(d_q, np.int64)
    mode  = np.broadcast_to(np.asarray(mode,  np.int64), (n,))
    train = np.broadcast_to(np.asarray(train, np.int64), (n,))
    wr, wi = [0]*n_taps, [0]*n_taps
    wr[n_taps//2] = 1 << wfrac                          # Center tap = 1.0.
    xr, xi = [0]*n_taps, [0]*n_taps                     # Input window (tap 0 = current).
    prev   = None                                       # (e, window) of the previous sample.
    out_i  = np.zeros(n, np.int64)
    out_q  = np.zeros(n, np.int64)
    for k in range(n):
        xr = [int(i[k])] + xr[:-1]
        xi = [int(q[k])] + xi[:-1]
        yi = int(np_scaled(sum(wr[t]*xr[t] - wi[t]*xi[t] for t in range(n_taps)), wfrac, W))
        yq = int(np_scaled(sum(wr[t]*xi[t] + wi[t]*xr[t] for t in range(n_taps)), wfrac, W))
        if mode[k] == 1:                                # CMA: e = y * (R2 - |y|^2) * 2**egain.
            dm  = int(cma_r2) - int(np_rounded(np.int64(yi*yi + yq*yq), F))
            e_i = int(np_scaled(np.int64(yi*dm), F - cma_egain, W + 1))
            e_q = int(np_scaled(np.int64(yq*dm), F - cma_egain, W + 1))
        elif mode[k] == 2:                              # DD: nearest QPSK point at dd_level.
            e_i = (int(dd_level) if yi >= 0 else -int(dd_level)) - yi
            e_q = (int(dd_level) if yq >= 0 else -int(dd_level)) - yq
        else:                                           # Trained: e = d - y.
            e_i = int(d_i[k]) - yi
            e_q = int(d_q[k]) - yq
        if train[k] and prev is not None:               # Delayed update: e[k-1] on window[k-1].
            pei, peq, pxr, pxi = prev
            for t in range(n_taps):
                wr[t] = int(np_saturated(np.int64(wr[t] + ((pei*pxr[t] + peq*pxi[t]) >> mu_shift)), ww))
                wi[t] = int(np_saturated(np.int64(wi[t] + ((peq*pxr[t] - pei*pxi[t]) >> mu_shift)), ww))
        prev = (e_i, e_q, list(xr), list(xi))
        out_i[k], out_q[k] = yi, yq
    return out_i, out_q

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

# AGC ----------------------------------------------------------------------------------------------

def agc_model(i, q, target, data_width=16, gain_frac=8, mu=8, gain_max=None, beta_shift=2):
    """Reference for litedsp.level.agc.LiteDSPAGC (bit-exact).

    Per accepted sample: apply the current gain (round-half-up + saturate), measure the output
    magnitude (alpha-max-beta-min), then integrate ``gain += (target - |y|) >> mu`` clamped to
    ``[0, gain_max]``. The gateware loop pauses with the stream, so the sequence is
    handshake-invariant and this model holds under backpressure too. Returns (i, q).
    """
    gain_width = gain_frac + data_width
    if gain_max is None:
        gain_max = (1 << gain_width) - 1
    gain = 1 << gain_frac                               # Start at 1.0 (Q?.gain_frac).
    out_i = np.zeros(len(i), np.int64)
    out_q = np.zeros(len(q), np.int64)
    for n, (xi, xq) in enumerate(zip(np.asarray(i, np.int64), np.asarray(q, np.int64))):
        yi = int(np_scaled(int(xi)*gain, gain_frac, data_width))
        yq = int(np_scaled(int(xq)*gain, gain_frac, data_width))
        ai, aq   = abs(yi), abs(yq)
        mag      = (ai + (aq >> beta_shift)) if ai > aq else (aq + (ai >> beta_shift))
        gain     = min(max(gain + ((target - mag) >> mu), 0), gain_max)  # >> is arithmetic.
        out_i[n] = yi
        out_q[n] = yq
    return out_i, out_q

# Magnitude ----------------------------------------------------------------------------------------

def magnitude_model(i, q, beta_shift=2):
    """Reference for litedsp.analysis.magnitude.Magnitude (alpha-max-beta-min)."""
    ai = np.abs(np.asarray(i, np.int64))
    aq = np.abs(np.asarray(q, np.int64))
    hi = np.maximum(ai, aq)
    lo = np.minimum(ai, aq)
    return hi + (lo >> beta_shift)

# Envelope Detector --------------------------------------------------------------------------------

def envelope_detector_model(i, q, attack=2, release=6, data_width=16, beta_shift=2):
    """Reference for litedsp.level.peak.LiteDSPEnvelopeDetector (gap-free input stream).

    Per sample: ``env += (|x| - env) >> attack`` when rising, ``>> release`` when falling
    (arithmetic shifts, matching the signed Migen shifts), with |x| the alpha-max-beta-min
    magnitude. Bit-exact against the HW when the input stream has no bubbles: the HW envelope
    register also steps on input-idle cycles (it re-evaluates the stale magnitude while the
    pipeline advances), i.e. it converges in cycle time rather than sample time. Output-side
    backpressure freezes the whole pipeline and is therefore safe.
    """
    mag = magnitude_model(i, q, beta_shift)
    env = 0
    out = np.zeros(len(mag), np.int64)
    for n, m in enumerate(mag):
        delta = int(m) - env
        env  += delta >> (attack if delta >= 0 else release)  # Python >> is arithmetic (floor).
        out[n] = env
    return out

# Slicer -------------------------------------------------------------------------------------------

def slicer_model(i, q, bits_per_axis=1, spacing=8192, data_width=16):
    """Reference for litedsp.comm.slicer.LiteDSPSlicer. Returns (i, q, symbol) arrays.

    Per axis: k = number of decision boundaries (at (2j - L + 2)*spacing, j = 0..L-2) at/below
    x; decided point = (2k - (L-1))*spacing. Symbol index is [q_bits | i_bits]. The point
    register is data_width bits wide, so out-of-range constellation points wrap like the HW.
    """
    L    = 1 << bits_per_axis
    i, q = np.asarray(i, np.int64), np.asarray(q, np.int64)
    def decide(x):
        k = np.zeros(len(x), np.int64)
        for j in range(L - 1):
            k += (x >= (2*j - L + 2)*spacing)
        point = (2*k - (L - 1))*spacing
        point = ((point + (1 << (data_width - 1))) & ((1 << data_width) - 1)) - (1 << (data_width - 1))
        return k, point
    ki, pi = decide(i)
    kq, pq = decide(q)
    return pi, pq, (kq << bits_per_axis) | ki

# Soft Demapper ------------------------------------------------------------------------------------

def soft_demap_model(i, q, bits_per_axis=1, spacing=8000, llr_bits=4, llr_scale=(1 << 15),
    scale_frac=15):
    """Reference for litedsp.comm.soft_demap.LiteDSPSoftDemapper. Returns the packed llrs array.

    Per axis, bit ``j`` of the Gray label ``g = k ^ (k >> 1)`` of the PAM level index gets the
    folded max-log LLR (positive = bit 0 more likely), in axis-LSB units:

        raw[B-1] = -x                                       (axis MSB)
        raw[j]   = |d[j+1]| - 2**(j+1)*spacing              (d[j] = -raw[j], d[B-1] = x)

    Each raw LLR is scaled by ``llr_scale/2**scale_frac`` (round half up), then saturated
    symmetrically to +/-(2**(llr_bits-1)-1). Output beat: 2*bits_per_axis LLRs packed LSB-first,
    I-axis bits first, Gray LSB (bit 0) first.
    """
    B    = bits_per_axis
    i, q = np.asarray(i, np.int64), np.asarray(q, np.int64)
    hi   = (1 << (llr_bits - 1)) - 1
    mask = (1 << llr_bits) - 1
    def axis_llrs(x):
        raws        = [None]*B
        d           = x
        raws[B - 1] = -d
        for j in range(B - 2, -1, -1):
            raws[j] = np.abs(d) - (1 << (j + 1))*spacing
            d       = -raws[j]
        return [np.clip(np_rounded(raws[j]*llr_scale, scale_frac), -hi, hi) for j in range(B)]
    packed = np.zeros(len(i), np.int64)
    for slot, v in enumerate(axis_llrs(i) + axis_llrs(q)):
        packed |= (v & mask) << (slot*llr_bits)
    return packed

# Viterbi Decoder ----------------------------------------------------------------------------------

def pack_llrs(llrs, llr_bits):
    """Pack per-symbol signed LLR lists into sink/source words (slot j at bits [j*k +: k])."""
    mask = (1 << llr_bits) - 1
    return [sum((int(l) & mask) << (j*llr_bits) for j, l in enumerate(sym)) for sym in llrs]

def viterbi_model(data, constraint=7, polys=(0o171, 0o133), traceback=None, llr_bits=None,
    metric_width=None):
    """Reference for litedsp.comm.viterbi.LiteDSPViterbiDecoder (hard and soft), bit-exact.

    ``data`` is a list of hard n-bit coded symbols when ``llr_bits`` is None, else of packed
    signed-LLR words (n*llr_bits wide, slot j = coded stream j, LSB-first — see
    :func:`pack_llrs`). Mirrors the RTL step-exactly: same reset penalty (state 0 favored),
    branch metrics (Hamming, or mismatched-|LLR| sum in soft mode), ACS tie-break (smaller
    predecessor wins), first-minimum global normalization and register-exchange output timing
    (the first traceback-1 symbols are absorbed; output k = message bit k).
    """
    n_bits    = len(polys)
    n_states  = 1 << (constraint - 1)
    mask      = n_states - 1
    traceback = traceback or 8*constraint
    bm_max    = n_bits if llr_bits is None else n_bits*(1 << (llr_bits - 1))
    if metric_width is None:
        metric_width = 10 if llr_bits is None else \
            max(10, ((constraint - 1)*bm_max).bit_length() + 2)
    big = 1 << (metric_width - 2)
    # Predecessor tables (mirror viterbi._transitions: preds appended in increasing p order).
    preds = [[] for _ in range(n_states)]
    for p in range(n_states):
        for b in (0, 1):
            full = b | (p << 1)
            sym  = 0
            for k, g in enumerate(polys):
                sym |= (bin(g & full).count("1") & 1) << k
            preds[full & mask].append((p, sym))
    p0 = np.array([preds[s][0][0] for s in range(n_states)])
    e0 = np.array([preds[s][0][1] for s in range(n_states)])
    p1 = np.array([preds[s][1][0] for s in range(n_states)])
    e1 = np.array([preds[s][1][1] for s in range(n_states)])
    lsb = np.arange(n_states) & 1
    metrics = np.full(n_states, big, np.int64)
    metrics[0] = 0
    survs   = np.zeros(n_states, np.int64)
    sv_mask = (1 << traceback) - 1
    llr_mask = (1 << (llr_bits or 1)) - 1
    out = []
    for step, d in enumerate(data):
        d = int(d)
        if llr_bits is None:
            bm = np.array([bin(d ^ sym).count("1") for sym in range(1 << n_bits)])
        else:
            llrs = [((d >> (j*llr_bits)) & llr_mask) - ((d >> (j*llr_bits + llr_bits - 1) & 1)
                    << llr_bits) for j in range(n_bits)]
            bm = np.array([sum(abs(l) for j, l in enumerate(llrs)
                               if (l < 0) != bool((sym >> j) & 1))
                           for sym in range(1 << n_bits)])
        m0  = metrics[p0] + bm[e0]
        m1  = metrics[p1] + bm[e1]
        sel = m1 < m0                                       # Ties keep predecessor 0.
        newm  = np.where(sel, m1, m0)
        newsv = ((survs[np.where(sel, p1, p0)] << 1) & sv_mask) | lsb
        best  = int(np.argmin(newm))                        # Ties keep the earlier state.
        metrics = newm - newm[best]
        survs   = newsv
        if step >= traceback - 1:
            out.append(int((survs[best] >> (traceback - 1)) & 1))
    return out

# Puncturer / Depuncturer ----------------------------------------------------------------------------

def puncture_model(symbols, pattern, n=2, phase=0):
    """Reference for litedsp.comm.puncture.LiteDSPPuncturer: serial kept bits (row 0 first)."""
    period = len(pattern[0])
    out = []
    for t, s in enumerate(symbols):
        col = (t + phase) % period
        for j in range(n):
            if pattern[j][col]:
                out.append((int(s) >> j) & 1)
    return out

def depuncture_model(llrs, pattern, n=2, llr_bits=4, phase=0):
    """Reference for litedsp.comm.puncture.LiteDSPDepuncturer: packed n-slot LLR words.

    ``llrs`` is the serial LLR stream (kept-bit order); punctured slots get LLR 0. Trailing
    LLRs that do not complete a pattern column are dropped (still buffered in hardware).
    """
    period = len(pattern[0])
    kept   = [[j for j in range(n) if pattern[j][t]] for t in range(period)]
    mask   = (1 << llr_bits) - 1
    out    = []
    t, k   = phase % period, 0
    while k + len(kept[t]) <= len(llrs):
        word = 0
        for j in kept[t]:
            word |= (int(llrs[k]) & mask) << (j*llr_bits)
            k += 1
        out.append(word)
        t = (t + 1) % period
    return out

# Reed-Solomon (GF(2^8)) ----------------------------------------------------------------------------
#
# Conventional-basis RS over GF(2^8) with field polynomial 0x11D (alpha = 2) and generator
# roots alpha^0 .. alpha^(2t-1) (fcr = 0) — the litedsp.comm.rs conventions (CCSDS 131.0-B uses
# 0x187 with dual-basis symbols; a basis-conversion wrapper is a documented follow-up there).

RS_GF_POLY = 0x11D

def gf_mul(a, b, poly=RS_GF_POLY):
    """GF(2^8) product (carry-less multiply reduced by ``poly``)."""
    r = 0
    a, b = int(a), int(b)
    while b:
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
        if a & 0x100:
            a ^= poly
    return r

def gf_tables(poly=RS_GF_POLY):
    """Antilog/log tables: ``exp[i] = alpha^i`` (256 entries, ``exp[255] = exp[0] = 1`` so the
    inverse address ``255 - log[x]`` stays in range), ``log[exp[i]] = i`` (``log[0]`` unused)."""
    exp = [0]*256
    log = [0]*256
    v = 1
    for i in range(255):
        exp[i] = v
        log[v] = i
        v = gf_mul(v, 2, poly)
    exp[255] = 1
    return exp, log

def rs_generator(n_parity, fcr=0):
    """RS generator polynomial g(x) = prod (x - alpha^(fcr+i)), ascending coefficients (monic)."""
    exp, _ = gf_tables()
    g = [1]
    for i in range(n_parity):
        root = exp[(fcr + i) % 255]
        ng = [0]*(len(g) + 1)
        for j, c in enumerate(g):
            ng[j]     ^= gf_mul(c, root)
            ng[j + 1] ^= c
        g = ng
    return g

def rs_encode_model(message, n=255, k=223):
    """Reference for litedsp.comm.rs.LiteDSPRSEncoder: k message bytes -> n-byte codeword.

    Systematic LFSR division by g(x); the 2t parity bytes follow the message, highest-degree
    coefficient first (mirrors the hardware drain order).
    """
    assert len(message) == k
    n_par = n - k
    g = rs_generator(n_par)
    p = [0]*n_par                       # p[i] = coefficient of x^i of the running remainder.
    for byte in message:
        fb = int(byte) ^ p[-1]
        p  = [gf_mul(fb, g[0])] + [p[i - 1] ^ gf_mul(fb, g[i]) for i in range(1, n_par)]
    return [int(byte) for byte in message] + p[::-1]

def rs_decode_model(codeword, n=255, k=223):
    """Reference for litedsp.comm.rs.LiteDSPRSDecoder; returns ``(message, corrected, uncorrectable)``.

    Full hard-decision decode (syndromes, Berlekamp-Massey, Chien, Forney), mirroring the
    hardware exactly — including the degree-t truncation of the BM register files and the
    root-count/locator-degree consistency check — so message bytes *and* status match
    bit-for-bit. An uncorrectable block returns the received message bytes unmodified with
    ``corrected = 0``.
    """
    exp, log = gf_tables()
    n_par = n - k
    t     = n_par//2
    rx    = [int(byte) for byte in codeword]
    assert len(rx) == n

    # Syndromes S_i = r(alpha^i) (Horner; arrival order = highest-degree coefficient first).
    synd = [0]*n_par
    for byte in rx:
        synd = [gf_mul(synd[i], exp[i]) ^ byte for i in range(n_par)]
    if not any(synd):
        return rx[:k], 0, False

    # Berlekamp-Massey, register files truncated at degree t (as in hardware).
    lam = [1] + [0]*t
    B   = [1] + [0]*t
    L, m, b = 0, 1, 1
    for r in range(n_par):
        d = 0
        for j in range(min(r, t) + 1):
            d ^= gf_mul(lam[j], synd[r - j])
        if d == 0:
            m += 1
            continue
        coef = gf_mul(d, exp[255 - log[b]])          # d/b via the log/antilog tables.
        swap = 2*L <= r
        old  = list(lam)
        for j in range(t + 1):
            lam[j] ^= gf_mul(coef, B[j - m]) if j >= m else 0
        if swap:
            B, L, b, m = old, r + 1 - L, d, 1
        else:
            m += 1
    if L > t:
        return rx[:k], 0, True

    # Omega = S(x)*lambda(x) mod x^2t (degree <= t-1).
    omg = [0]*t
    for j in range(t):
        for l in range(j + 1):
            omg[j] ^= gf_mul(synd[l], lam[j - l])

    # Chien scan over all n positions (X = alpha^i <-> coefficient of x^i, buffer index
    # n-1-i) with Forney magnitudes Omega(X^-1)/odd(lambda(X^-1)) (the fcr = 0 form).
    q = list(lam)
    o = list(omg)
    roots, anomaly = [], False
    for i in range(n):
        odd  = 0
        even = 0
        for j in range(t + 1):
            if j % 2:
                odd ^= q[j]
            else:
                even ^= q[j]
        if (even ^ odd) == 0:
            if odd == 0:
                anomaly = True                       # Degenerate (repeated root).
            else:
                om_val = 0
                for j in range(t):
                    om_val ^= o[j]
                roots.append((n - 1 - i, gf_mul(om_val, exp[255 - log[odd]])))
        q = [gf_mul(q[j], exp[(255 - j) % 255]) for j in range(t + 1)]
        o = [gf_mul(o[j], exp[(255 - j) % 255]) for j in range(t)]

    if anomaly or len(roots) != L:
        return rx[:k], 0, True
    for idx, mag in roots:
        rx[idx] ^= mag
    return rx[:k], len(roots), False

# Differential Encoder / Decoder -------------------------------------------------------------------

def diff_encode_model(symbols, modulus=4):
    """Reference for litedsp.comm.diff.LiteDSPDifferentialEncoder: out[n] = (in[n] + out[n-1]) mod M."""
    acc = 0
    out = np.zeros(len(symbols), np.int64)
    for n, s in enumerate(symbols):
        acc    = (acc + int(s)) % modulus
        out[n] = acc
    return out

def diff_decode_model(symbols, modulus=4):
    """Reference for litedsp.comm.diff.LiteDSPDifferentialDecoder: out[n] = (in[n] - in[n-1]) mod M."""
    prev = 0
    out  = np.zeros(len(symbols), np.int64)
    for n, s in enumerate(symbols):
        out[n] = (int(s) - prev) % modulus
        prev   = int(s)
    return out

# Frame Sync ---------------------------------------------------------------------------------------

def frame_sync_model(i, q, sequence, threshold, data_width=16, threshold_frac=14,
    frame_len=None, peak_window=4, offset=0):
    """Reference for litedsp.comm.frame_sync.LiteDSPFrameSync (bit-exact, sample domain).

    Returns ``(i, q, first, last, peaks)``: the aligned output stream is the input unchanged
    (the hardware is a pure sample delay), ``first``/``last`` are 0/1 arrays tagging the
    frame boundaries on the output samples, ``peaks`` lists the accepted correlation-peak
    sample indexes. The correlation is the same complex FIR as the gateware
    (``fir_complex_model`` with the shared ``frame_sync_taps`` quantization, saturating
    recombine for complex sequences); the energy window, threshold compare (both sides wide
    and exact) and the peak-pick/alignment FSM mirror the RTL step for step. int64 holds the
    compare exactly for data_width <= 16 and threshold_frac + 2*ceil(log2(N)) <= 30.
    """
    from litedsp.comm.frame_sync import frame_sync_taps
    i, q  = np.asarray(i, np.int64), np.asarray(q, np.int64)
    n     = len(sequence)
    W     = peak_window
    coeffs_r, coeffs_i = frame_sync_taps(sequence, data_width)
    # Correlation (matched filter): corr = x (*) conj(reversed(sequence)).
    a_i, a_q = fir_complex_model(i, q, coeffs_r, data_width)
    if any(coeffs_i):
        b_i, b_q = fir_complex_model(i, q, coeffs_i, data_width)
        corr_i = np_saturated(a_i - b_q, data_width)
        corr_q = np_saturated(a_q + b_i, data_width)
    else:
        corr_i, corr_q = a_i, a_q
    mag2 = corr_i*corr_i + corr_q*corr_q
    # Moving energy window over the sequence length (zeros before the stream) + CFAR compare.
    # A zero-energy window (dead line) never detects: 0 >= 0 does not count as a crossing.
    energy = np.convolve(i*i + q*q, np.ones(n, np.int64))[:len(i)]
    exceed = (energy > 0) & ((mag2 << threshold_frac) >= threshold*n*energy)
    # Peak-pick / alignment FSM (one iteration per sample, mirroring the RTL steps; the
    # output register trails the FSM plane by W-1 samples, hence the k - (W-1) tag indexes).
    first = np.zeros(len(i), np.int64)
    last  = np.zeros(len(i), np.int64)
    peaks = []
    state = "idle"
    best = b_off = s_cnt = a_cnt = f_cnt = 0
    for k in range(len(i)):
        if state == "idle":
            if exceed[k]:
                if W == 1:
                    peaks.append(k)
                    a_cnt, state = 1 + offset, "align"
                else:
                    best, b_off, s_cnt, state = int(mag2[k]), 0, 1, "search"
        elif state == "search":
            bo = s_cnt if mag2[k] > best else b_off
            if mag2[k] > best:
                best, b_off = int(mag2[k]), s_cnt
            if s_cnt == W - 1:  # Window complete: peak known.
                peaks.append(k - (W - 1) + bo)
                a_cnt, state = bo + 1 + offset, "align"
            s_cnt += 1
        elif state == "align":
            if a_cnt == 1:
                out = k - (W - 1)   # Sample entering the output register this step.
                if out < len(first):
                    first[out] = 1
                if frame_len is None:
                    state = "idle"
                elif frame_len == 1:
                    if out < len(last):
                        last[out] = 1
                    state = "idle"
                else:
                    f_cnt, state = frame_len - 1, "frame"
            else:
                a_cnt -= 1
        else:  # frame
            if f_cnt == 1:
                out = k - (W - 1)
                if out < len(last):
                    last[out] = 1
                state = "idle"
            else:
                f_cnt -= 1
    return i, q, first, last, peaks

# Stream Ops ---------------------------------------------------------------------------------------

def _np_wrapped(v, width):
    """Wrap to signed ``width``-bit two's-complement (register truncation, no saturation)."""
    v = np.asarray(v, np.int64) & ((1 << width) - 1)
    return np.where(v >= (1 << (width - 1)), v - (1 << width), v)

def conjugate_model(i, q, data_width=16):
    """Reference for litedsp.stream.ops.LiteDSPConjugate (q -> -q; -full-scale wraps, no saturation)."""
    return np.asarray(i, np.int64), _np_wrapped(-np.asarray(q, np.int64), data_width)

def swap_iq_model(i, q, data_width=16):
    """Reference for litedsp.stream.ops.LiteDSPSwapIQ (i <-> q)."""
    return np.asarray(q, np.int64), np.asarray(i, np.int64)

def negate_model(i, q, data_width=16):
    """Reference for litedsp.stream.ops.LiteDSPNegate (-full-scale wraps, no saturation)."""
    return (_np_wrapped(-np.asarray(i, np.int64), data_width),
            _np_wrapped(-np.asarray(q, np.int64), data_width))

def iq_add_model(a_i, a_q, b_i, b_q, data_width=16):
    """Reference for litedsp.stream.ops.LiteDSPIQAdd (saturating complex add)."""
    a_i, a_q = np.asarray(a_i, np.int64), np.asarray(a_q, np.int64)
    b_i, b_q = np.asarray(b_i, np.int64), np.asarray(b_q, np.int64)
    return np_saturated(a_i + b_i, data_width), np_saturated(a_q + b_q, data_width)

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

def _bit_reverse(k, bits):
    r = 0
    for _ in range(bits):
        r = (r << 1) | (k & 1)
        k >>= 1
    return r

def fft_fixed_model(frame_i, frame_q, data_width=16, twiddle_width=16):
    """Bit-exact reference for litedsp.analysis.fft.LiteDSPFFT (radix-2 SDF, DIF).

    Iterative in-place DIF with the gateware's fixed-point arithmetic per stage: butterfly sum
    scaled by 1/2 (round half-up + saturate), difference multiplied by the quantized Q1.(W-1)
    twiddle and rescaled. Returns (i, q) int arrays in the FFT's **bit-reversed** output order.
    """
    xi    = np.asarray(frame_i, np.int64).copy()
    xq    = np.asarray(frame_q, np.int64).copy()
    N     = len(xi)
    bits  = N.bit_length() - 1
    scale = (1 << (twiddle_width - 1)) - 1
    for s in range(bits):
        D  = N >> (s + 1)
        tr = np.array([int(round(math.cos(-math.pi*p/D)*scale)) for p in range(D)], np.int64)
        ti = np.array([int(round(math.sin(-math.pi*p/D)*scale)) for p in range(D)], np.int64)
        for b in range(0, N, 2*D):
            for p in range(D):
                ai, aq = xi[b + p],     xq[b + p]
                bi, bq = xi[b + p + D], xq[b + p + D]
                dr, di = ai - bi, aq - bq
                xi[b + p] = np_scaled(ai + bi, 1, data_width)
                xq[b + p] = np_scaled(aq + bq, 1, data_width)
                if D > 1:
                    xi[b + p + D] = np_scaled(dr*tr[p] - di*ti[p], twiddle_width, data_width)
                    xq[b + p + D] = np_scaled(dr*ti[p] + di*tr[p], twiddle_width, data_width)
                else:
                    xi[b + p + D] = np_scaled(dr, 1, data_width)
                    xq[b + p + D] = np_scaled(di, 1, data_width)
    return xi, xq

def fft_bfp_model(i, q, N, data_width=16, twiddle_width=16):
    """Bit-exact reference for litedsp.analysis.fft.LiteDSPFFT with ``scaling="bfp"``.

    Processes ``len(i)//N`` consecutive frames with the gateware's per-stage block-floating-
    point state: at each stage, all of frame k's butterflies are scaled by 1/2 iff some
    butterfly output of frame k-1 at that stage overflowed the unshifted ``data_width`` range
    (the sum ``a + b`` checked directly, the twiddled difference after its
    ``twiddle_width - 1`` product rounding); frame 0 is unscaled at every stage, and a frame
    whose one-frame-delayed decision under-predicts saturates (round + saturate). Returns
    ``(i, q, exp)``: the concatenated **bit-reversed**-order frames and one exponent per
    frame — the number of halvings applied, so a frame's values are ``DFT(x)/2**exp`` up to
    rounding/saturation (``exp == log2(N)`` every frame reproduces "scaled" mode bit-exactly).
    """
    i     = np.asarray(i, np.int64)
    q     = np.asarray(q, np.int64)
    bits  = N.bit_length() - 1
    scale = (1 << (twiddle_width - 1)) - 1
    hi    =  (1 << (data_width - 1)) - 1
    lo    = -(1 << (data_width - 1))
    def ovf(*values):
        return any(v > hi or v < lo for v in values)
    tw = []
    for s in range(bits):
        D = N >> (s + 1)
        tw.append(([int(round(math.cos(-math.pi*p/D)*scale)) for p in range(D)],
                   [int(round(math.sin(-math.pi*p/D)*scale)) for p in range(D)]))
    sh = [0]*bits                            # Per-stage shift decision (from previous frame).
    out_i, out_q, exps = [], [], []
    for f in range(len(i)//N):
        xi  = i[f*N:(f + 1)*N].copy()
        xq  = q[f*N:(f + 1)*N].copy()
        exp = 0
        for s in range(bits):
            D      = N >> (s + 1)
            tr, ti = tw[s]
            shift  = sh[s]
            det    = False
            for b in range(0, N, 2*D):
                for p in range(D):
                    ai, aq = int(xi[b + p]),     int(xq[b + p])
                    bi, bq = int(xi[b + p + D]), int(xq[b + p + D])
                    dr, di = ai - bi, aq - bq
                    det   |= ovf(ai + bi, aq + bq)
                    xi[b + p] = np_scaled(ai + bi, shift, data_width)
                    xq[b + p] = np_scaled(aq + bq, shift, data_width)
                    if D > 1:
                        pr, pq = dr*tr[p] - di*ti[p], dr*ti[p] + di*tr[p]
                        det   |= ovf(int(np_rounded(np.int64(pr), twiddle_width - 1)),
                                     int(np_rounded(np.int64(pq), twiddle_width - 1)))
                        xi[b + p + D] = np_scaled(pr, twiddle_width - 1 + shift, data_width)
                        xq[b + p + D] = np_scaled(pq, twiddle_width - 1 + shift, data_width)
                    else:
                        det |= ovf(dr, di)
                        xi[b + p + D] = np_scaled(dr, shift, data_width)
                        xq[b + p + D] = np_scaled(di, shift, data_width)
            sh[s] = int(det)
            exp  += shift
        out_i.append(xi)
        out_q.append(xq)
        exps.append(exp)
    return np.concatenate(out_i), np.concatenate(out_q), np.array(exps, np.int64)

# Window -------------------------------------------------------------------------------------------

def window_model(i, q, coeffs, data_width=16):
    """Reference for litedsp.analysis.window.Window (per-frame coeff multiply + round/saturate)."""
    i, q   = np.asarray(i, np.int64), np.asarray(q, np.int64)
    n      = len(coeffs)
    w      = np.array([coeffs[k % n] for k in range(len(i))], dtype=np.int64)
    shift  = data_width - 1
    return np_scaled(i*w, shift, data_width), np_scaled(q*w, shift, data_width)

# PSD ----------------------------------------------------------------------------------------------

def psd_model(i, q, N, avg_log2=4, mode=0, clears=()):
    """Reference for litedsp.analysis.psd.LiteDSPPSD (per-bin power combining, all modes).

    ``i``/``q`` are the FFT-output samples in arrival (bit-reversed) order; one spectrum is
    emitted per ``2**avg_log2`` frames, in natural bin order. ``mode``: 0 = linear average,
    1 = exponential/leaky, 2 = max-hold, 3 = min-hold. ``clears`` is a set of frame indices
    that re-initialize the accumulator (mirroring a ``clear`` pulse during the preceding
    frame). Returns the list of emitted spectra.
    """
    i, q    = np.asarray(i, np.int64), np.asarray(q, np.int64)
    bits    = N.bit_length() - 1
    acc     = np.zeros(N, dtype=np.int64)
    spectra = []
    frame_cnt = 0
    for f in range(len(i)//N):
        init = (f == 0) or (f in clears) or ((mode == 0) and (frame_cnt == 0))
        for k in range(N):
            inst = int(i[f*N + k])**2 + int(q[f*N + k])**2
            a    = _bit_reverse(k, bits)
            if init:
                acc[a] = inst
            elif mode == 0:
                acc[a] = acc[a] + inst
            elif mode == 1:
                acc[a] = acc[a] + ((inst - acc[a]) >> avg_log2)
            elif mode == 2:
                acc[a] = max(acc[a], inst)
            else:
                acc[a] = min(acc[a], inst)
        frame_cnt += 1
        if frame_cnt == (1 << avg_log2):
            frame_cnt = 0
            spectra.append((acc >> avg_log2).copy() if mode == 0 else acc.copy())
    return spectra

# Welch PSD ----------------------------------------------------------------------------------------

def welch_model(i, q, N, avg_log2=2, window="hann", overlap=0, data_width=16):
    """Reference for litedsp.analysis.welch.LiteDSPWelchPSD (Window -> FFT -> PSD, overlapped).

    Segments ``i``/``q`` into ``N``-sample segments with a hop of ``N*(100-overlap)/100``
    samples, windows each segment (window_model), transforms it (fft_fixed_model) and
    combines per-bin power (psd_model, linear mode). Bit-exact against the gateware chain.
    Returns the list of emitted spectra (natural bin order), one per ``2**avg_log2`` segments.
    """
    from litedsp.analysis.window import window_coefficients
    coeffs = window_coefficients(N, window, data_width)
    i, q   = np.asarray(i, np.int64), np.asarray(q, np.int64)
    step   = N - (N*overlap)//100
    si, sq = [], []
    for start in range(0, len(i) - N + 1, step):
        wi, wq = window_model(i[start:start + N], q[start:start + N], coeffs, data_width)
        fi, fq = fft_fixed_model(wi, wq, data_width)
        si.append(fi)
        sq.append(fq)
    if not si:
        return []
    return psd_model(np.concatenate(si), np.concatenate(sq), N, avg_log2=avg_log2, mode=0)

# CORDIC (vectoring) -------------------------------------------------------------------------------

def cordic_vectoring_model(x, y, data_width=16, angle_width=16, stages=None):
    """Bit-exact angle of litedsp.generation.cordic.LiteDSPCORDIC vectoring (one vector).

    Mirrors the RTL stage recurrence exactly: quadrant pre-rotation, per-stage arithmetic
    shifts (floor, like migen's signed ``>>``) and the same angle_width-quantized atan LUT,
    all in the RTL's guarded widths (W = data_width + 2, Wz = angle_width + 2). Returns the
    signed ``angle_width``-bit angle (full circle = 2**angle_width). The magnitude path (1/K
    compensation) is not modeled — the CFO estimator consumes the angle only.
    """
    if stages is None:
        stages = data_width
    W, Wz = data_width + 2, angle_width + 2
    PI    = 1 << (angle_width - 1)
    atan  = [int(round(math.atan(2.0**(-i))/(2*math.pi)*(1 << angle_width))) for i in range(stages)]
    wx, wz = _wrapper(W), _wrapper(Wz)
    x, y  = int(x), int(y)
    # Pre-rotation into the convergence region.
    if x < 0:
        x, y, z = -x, -y, (-PI if y < 0 else PI)
    else:
        z = 0
    x, y, z = wx(x), wx(y), wz(z)
    # Iterations (d = -sign(y): drive y -> 0).
    for i in range(stages):
        sh_x, sh_y = x >> i, y >> i
        if y < 0:
            x, y, z = wx(x - sh_y), wx(y + sh_x), wz(z - atan[i])
        else:
            x, y, z = wx(x + sh_y), wx(y - sh_x), wz(z + atan[i])
    return _wrapper(angle_width)(z)

# Coarse CFO Estimator ------------------------------------------------------------------------------

def cfo_estimator_model(i, q, delay=16, span_log2=8, angle_width=16, phase_bits=32,
    data_width=16):
    """Bit-exact reference for litedsp.comm.cfo_est.LiteDSPCFOEstimator.

    ``i``/``q`` are the accepted input samples (the estimator is sample-domain, so results
    are invariant to valid/ready stall patterns). Products ``r[n] = x[n]*conj(x[n-delay])``
    (``x[n<0] = 0``, matching the zero-initialized delay line) are accumulated exactly over
    ``2**span_log2`` samples; each completed span yields ``angle(R)`` via
    :func:`cordic_vectoring_model` at the full accumulator width and the derotator correction
    ``(angle << (phase_bits - angle_width - log2(delay))) mod 2**phase_bits`` (the cancelling
    minus sign is the derotator's down-mixer). Returns ``(angles, phase_incs)``, one entry
    per completed span.
    """
    N          = 1 << span_log2
    acc_width  = 2*data_width + 1 + span_log2
    shift      = phase_bits - angle_width - (delay.bit_length() - 1)
    i          = [int(v) for v in i]
    q          = [int(v) for v in q]
    angles, phase_incs = [], []
    acc_i = acc_q = 0
    for n in range(len(i)):
        di = i[n - delay] if n >= delay else 0
        dq = q[n - delay] if n >= delay else 0
        acc_i += i[n]*di + q[n]*dq
        acc_q += q[n]*di - i[n]*dq
        if (n + 1) % N == 0:
            ang = cordic_vectoring_model(acc_i, acc_q, data_width=acc_width,
                angle_width=angle_width, stages=angle_width)
            angles.append(ang)
            phase_incs.append((ang << shift) & ((1 << phase_bits) - 1))
            acc_i = acc_q = 0
    return angles, phase_incs

# OFDM Equalizer ------------------------------------------------------------------------------------

def ofdm_equalizer_model(i, q, train, fft_size=64, ref=None, coeff_frac=14, data_width=16):
    """Bit-exact reference for litedsp.comm.ofdm_eq.LiteDSPOFDMEqualizer.

    ``i``/``q`` are the accepted input samples, whole ``fft_size``-beat frames; ``train`` is
    one boolean per frame (True = that frame is consumed as the preamble). ``ref`` is the
    2-bit-per-bin reference RAM contents (bit 0 = I sign, bit 1 = Q sign, 1 = positive;
    default = all 0b11 = 1 + 1j). H resets to 1.0 + 0j (``1 << coeff_frac``) per bin; a
    training frame stores ``H_k = scaled(Y_k * conj(X_ref_k), 1)`` and emits nothing, every
    other frame emits ``S_k = scaled(Y_k * conj(H_k), coeff_frac)`` and
    ``csi_k = scaled(|H_k|**2, coeff_frac)``. Returns ``(i, q, csi)`` int arrays over the
    non-training frames, in input (frame-position) bin order.
    """
    i = np.asarray(i, np.int64)
    q = np.asarray(q, np.int64)
    if ref is None:
        ref = [0b11]*fft_size
    si  = np.where(np.asarray(ref, np.int64) & 0b01, 1, -1)   # I sign per bin.
    sq  = np.where(np.asarray(ref, np.int64) & 0b10, 1, -1)   # Q sign per bin.
    h_i = np.full(fft_size, 1 << coeff_frac, np.int64)        # H reset = 1.0 + 0j.
    h_q = np.zeros(fft_size, np.int64)
    out_i, out_q, out_csi = [], [], []
    for f in range(len(i)//fft_size):
        yi = i[f*fft_size:(f + 1)*fft_size]
        yq = q[f*fft_size:(f + 1)*fft_size]
        if f < len(train) and train[f]:                       # LS estimation: H = Y*conj(X_ref)/2.
            h_i = np_scaled(yi*si + yq*sq, 1, data_width)
            h_q = np_scaled(yq*si - yi*sq, 1, data_width)
        else:                                                 # One-tap equalize: S = Y*conj(H).
            out_i.append(np_scaled(yi*h_i + yq*h_q, coeff_frac, data_width))
            out_q.append(np_scaled(yq*h_i - yi*h_q, coeff_frac, data_width))
            out_csi.append(np_scaled(h_i*h_i + h_q*h_q, coeff_frac, data_width))
    if not out_i:
        empty = np.zeros(0, np.int64)
        return empty, empty.copy(), empty.copy()
    return np.concatenate(out_i), np.concatenate(out_q), np.concatenate(out_csi)

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
