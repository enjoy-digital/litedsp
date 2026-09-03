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

import random

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

def carrier_loop_model(i, q, detector="pll", data_width=16, phase_bits=32,
    lut_depth=1024, kp_shift=6, ki_shift=14, loop_delay=1):
    """Bit-exact reference for :class:`LiteDSPCarrierLoop`.

    The NCO uses the phase at the start of each accepted sample. ``loop_delay`` is the number
    of accepted samples from detecting an error until it changes the phase seen by a later
    sample (one for classic, four for the timing-oriented pipeline). The proportional phase
    update and integral update both see the old integral value, exactly as synchronous RTL does.
    PI state and the phase accumulator wrap in two's complement; only complex derotation is
    rounded and saturated.
    """
    if detector not in ("pll", "bpsk", "qpsk"):
        raise ValueError("detector must be 'pll', 'bpsk', or 'qpsk'")
    addr_bits    = int(round(np.log2(lut_depth)))
    cos_t, sin_t = nco_lut(lut_depth, data_width)
    phase_mask   = (1 << phase_bits) - 1
    loop_width   = phase_bits + 2
    loop_wrap    = _wrapper(loop_width)
    phase        = 0
    integral     = 0
    pending      = []
    out_i, out_q = [], []
    for xn_i, xn_q in zip(i, q):
        addr = phase >> (phase_bits - addr_bits)
        c, s = int(cos_t[addr]), int(sin_t[addr])
        d_i = int(np_scaled(int(xn_i)*c + int(xn_q)*s, data_width - 1, data_width))
        d_q = int(np_scaled(int(xn_q)*c - int(xn_i)*s, data_width - 1, data_width))
        if detector == "bpsk":
            error = d_q if d_i >= 0 else -d_q
        elif detector == "qpsk":
            error = (d_q if d_i >= 0 else -d_q) - (d_i if d_q >= 0 else -d_i)
        else:
            error = d_q
        error = loop_wrap(error << (phase_bits - data_width))
        out_i.append(d_i)
        out_q.append(d_q)
        pending.append(error)
        if len(pending) >= loop_delay:
            update = pending.pop(0)
            loop_out = loop_wrap(integral + (update >> kp_shift))
            phase    = (phase + loop_out) & phase_mask
            integral = loop_wrap(integral + (update >> ki_shift))
    return np.asarray(out_i, np.int64), np.asarray(out_q, np.int64)

# Timing recovery ----------------------------------------------------------------------------------

def timing_recovery_model(i, q, data_width=16, sps=2, frac=16, gain_mu=0.1,
    gain_omega=None, ted="mm"):
    """Bit-exact accepted-sample reference for :class:`LiteDSPTimingRecovery`.

    The RTL's classic and pipelined loop-update architectures are numerically identical; the
    latter spends two extra clocks registering the completed interpolation sum and the
    already-computed gain corrections. This model
    therefore advances only on accepted input/output samples and intentionally has no
    ``architecture`` argument.

    It reproduces the registered Catmull-Rom interpolator, M&M/Gardner error quantization,
    signed controller widths, omega clamp, fractional-mu wrap, and data-dependent 1/2/3-sample
    slips. Returned arrays contain every complete output that can be formed from ``i``/``q``.
    """
    if ted not in ("mm", "gardner"):
        raise ValueError("ted must be 'mm' or 'gardner'")
    if gain_omega is None:
        gain_omega = gain_mu*gain_mu/4
    if len(i) != len(q):
        raise ValueError("i and q must have the same length")

    W          = data_width
    ONE        = 1 << frac
    gm_q       = int(round(gain_mu*ONE))
    go_q       = int(round(gain_omega*ONE))
    amp_shift  = W - 1
    omega_mid  = sps*ONE
    omega_lim  = int(round(0.05*sps*ONE))
    iw         = frac + 4
    nw         = 4 if ted == "mm" else 5
    wrap_iw    = _wrapper(iw)
    wrap_mu_n  = _wrapper(iw + 1)
    wrap_err   = _wrapper(W + 3)
    wrap_a1    = _wrapper(W + 2)
    wrap_a     = _wrapper(W + 4)
    wrap_y     = _wrapper(W + 6)

    def interp(w, mu_f):
        # Width truncations mirror the registered Signals in timing_recovery.py.
        a0 = int(w[1])
        a1 = wrap_a1((int(w[2]) - int(w[0])) >> 1)
        a2 = wrap_a((2*int(w[0]) - 5*int(w[1]) + 4*int(w[2]) - int(w[3])) >> 1)
        a3 = wrap_a((-int(w[0]) + 3*int(w[1]) - 3*int(w[2]) + int(w[3])) >> 1)
        y2 = wrap_y(a2 + ((mu_f*a3) >> frac))
        y1 = wrap_y(a1 + ((mu_f*y2) >> frac))
        return int(np_scaled(a0*ONE + mu_f*y1, frac, W))

    wr, wi     = [0]*nw, [0]*nw
    last_r     = last_q = 0
    mu         = ONE//2
    omega      = omega_mid
    nominal    = False
    pos        = 0
    need       = nw
    out_i, out_q = [], []

    xi = [int(v) for v in i]
    xq = [int(v) for v in q]
    while pos + need <= len(xi):
        for _ in range(need):
            wr = wr[1:] + [_wrapper(W)(xi[pos])]
            wi = wi[1:] + [_wrapper(W)(xq[pos])]
            pos += 1

        mu_f = mu & (ONE - 1)
        yr   = interp(wr[nw - 4:], mu_f)
        yq   = interp(wi[nw - 4:], mu_f)
        if ted == "mm":
            def sgnmul(sign_src, value):
                return value if sign_src >= 0 else -value
            err = wrap_err(sgnmul(last_r, yr) + sgnmul(last_q, yq)
                         - sgnmul(yr, last_r) - sgnmul(yq, last_q))
        else:
            ymid_r = interp(wr[:4], mu_f)
            ymid_q = interp(wi[:4], mu_f)
            g      = (last_r - yr)*ymid_r + (last_q - yq)*ymid_q
            gs     = g >> (W - 5)
            err    = int(np_saturated(gs, W + 3)) if nominal else 0

        omega_n = wrap_iw(omega + ((go_q*err) >> amp_shift))
        mu_n    = wrap_mu_n(mu + omega + ((gm_q*err) >> amp_shift))
        omega   = min(omega_mid + omega_lim, max(omega_mid - omega_lim, omega_n))
        step    = (mu_n & ((1 << (iw + 1)) - 1)) >> frac
        need    = step if step else 1
        mu      = mu_n & (ONE - 1)
        nominal = need == sps
        last_r, last_q = yr, yq
        out_i.append(yr)
        out_q.append(yq)

    return np.asarray(out_i, np.int64), np.asarray(out_q, np.int64)

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

# CFR (Peak Cancellation) ---------------------------------------------------------------------------

def cfr_model(i, q, threshold, pulse, data_width=16, beta_shift=2, index_bits=6,
    recip_frac=15, pipeline=0, correction_pipeline=False):
    """Reference for litedsp.level.cfr.LiteDSPCFR (bit-exact). Returns (i, q, peaks, missed).

    Per accepted sample: estimate the magnitude (alpha-max-beta-min), detect a peak on the
    *previous* sample (above threshold, >= current estimate, > the one before), and — when
    the single pulse engine is idle — fire a cancellation pulse: the complex amplitude is
    ``a = g * x_pk`` with ``g = (|x_pk| - T)/|x_pk|`` computed divider-free (leading-zero
    normalization + 64-entry midpoint reciprocal LUT, Q0.15, round-half-up, clamped), and
    ``a * pulse[k]`` (round + saturate at each step) is subtracted from the stream delayed
    by ``len(pulse)//2 + 2 + pipeline + correction_pipeline`` samples so the pulse center lands on the peak. Peaks detected
    while the engine is busy pass uncorrected (``missed``). All state advances on accepted
    samples only, so the sequence is handshake-invariant (holds under backpressure).

    ``pulse`` must be the block's quantized taps (litedsp.level.cfr.cfr_pulse); the LUT
    below mirrors litedsp.level.cfr.cfr_recip_lut.
    """
    W    = data_width
    L    = len(pulse)
    D    = (L - 1)//2 + 2 + pipeline + int(correction_pipeline)
    lut  = [int(round((1 << recip_frac)/(1 + (k + 0.5)/(1 << index_bits))))
            for k in range(1 << index_bits)]
    gmax = (1 << (W - 1)) - 1
    i, q  = np.asarray(i, np.int64), np.asarray(q, np.int64)
    out_i = np.zeros(len(i), np.int64)
    out_q = np.zeros(len(i), np.int64)
    busy, k, a_i, a_q = False, 0, 0, 0
    pending = None                    # (accepted samples remaining, a_i, a_q).
    corr_i_d = corr_q_d = 0
    p_i = p_q = 0                  # Peak candidate (previous sample).
    m1  = m2  = 0                  # Magnitude estimate one/two samples ago.
    peaks = missed = 0
    for n in range(len(i)):
        xi, xq = int(i[n]), int(q[n])
        ai, aq = abs(xi), abs(xq)
        mag = (ai + (aq >> beta_shift)) if ai > aq else (aq + (ai >> beta_shift))
        # Correction of the delayed sample (engine state as set by previous samples).
        di = int(i[n - D]) if n >= D else 0
        dq = int(q[n - D]) if n >= D else 0
        ci_now = int(np_rounded(a_i*pulse[k], W - 1)) if busy else 0
        cq_now = int(np_rounded(a_q*pulse[k], W - 1)) if busy else 0
        if correction_pipeline:
            ci, cq = corr_i_d, corr_q_d
            corr_i_d, corr_q_d = ci_now, cq_now
        else:
            ci, cq = ci_now, cq_now
        out_i[n] = np_saturated(di - ci, W)
        out_q[n] = np_saturated(dq - cq, W)
        # Engine index update + detection (fire tests the pre-update busy, like the RTL).
        reserved_pre = busy or (pending is not None)
        if busy:
            k += 1
            if k == L:
                busy = False
        if pending is not None:
            remain, pa_i, pa_q = pending
            remain -= 1
            if remain == 0:
                busy, k, a_i, a_q = True, 0, pa_i, pa_q
                pending = None
            else:
                pending = (remain, pa_i, pa_q)
        if (m1 > threshold) and (m1 >= mag) and (m1 > m2):
            if not reserved_pre:
                d   = m1 - threshold
                e   = W - int(m1).bit_length()
                mn  = m1 << e
                idx = (mn >> (W - 1 - index_bits)) & ((1 << index_bits) - 1)
                g   = min(int(np_rounded((d << e)*lut[idx], recip_frac)), gmax)
                na_i = int(np_scaled(g*p_i, W - 1, W))
                na_q = int(np_scaled(g*p_q, W - 1, W))
                if pipeline:
                    pending = (pipeline, na_i, na_q)
                else:
                    a_i, a_q, busy, k = na_i, na_q, True, 0
                peaks  += 1
            else:
                missed += 1
        p_i, p_q, m2, m1 = xi, xq, m1, mag
    return out_i, out_q, peaks, missed

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

def cic_decimator_model(x, R, N=3, M=1, data_width=16, shift=None, wrap_width=None):
    """Cycle-accurate reference for litedsp.filter.cic.CICDecimator (one channel).

    ``shift`` (default: the exact gain ``ceil(N*log2(R*M))``) and ``wrap_width`` (default:
    ``data_width + growth``) model the runtime variant, whose rescale shift is a control and
    whose registers are sized ``in_width + growth(r_max)`` (LiteDSPCICDecimatorRuntime).
    """
    growth = _cic_growth(R, N, M)
    wrap   = _wrapper(data_width + growth if wrap_width is None else wrap_width)
    if shift is None:
        shift = growth
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
            out.append(np_scaled(np.int64(c), shift, data_width))
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

def farm_model(inputs, coeffs, R, data_width=16, shift=None):
    """Reference for litedsp.rate.farm.LiteDSPResamplerFarm.

    ``inputs`` is a list of per-channel ``(i, q)`` sample arrays (the demuxed streams); each
    channel is exactly an independent :func:`fir_decimator_model`. ``coeffs`` can be one
    shared tap sequence or one sequence per channel. Returns the per-channel list of decimated
    ``(i, q)`` arrays.
    """
    banked = len(coeffs) == len(inputs) and all(hasattr(c, "__len__") for c in coeffs)
    taps = coeffs if banked else [coeffs]*len(inputs)
    return [(fir_decimator_model(i, taps[k], R, data_width, shift),
             fir_decimator_model(q, taps[k], R, data_width, shift))
            for k, (i, q) in enumerate(inputs)]

def fir_interpolator_model(x, coeffs, L, data_width=16, shift=None):
    """Reference for litedsp.filter.fir_poly.FIRInterpolator (one channel)."""
    if shift is None:
        shift = data_width - 1
    up        = np.zeros(len(x)*L, np.int64)
    up[::L]   = np.asarray(x, np.int64)
    conv      = np.convolve(up, np.asarray(coeffs, np.int64))[:len(up)]
    return np_scaled(conv, shift, data_width)

# PFB Channelizer ----------------------------------------------------------------------------------

def pfb_channelizer_model(i, q, coefficients, n_channels, data_width=16, oversampling=1):
    """Bit-exact reference for litedsp.mixing.pfb_channelizer.LiteDSPPFBChannelizer.

    Uniform DFT filter bank with hop ``H=M/oversampling``. Per frame m (newest sample index
    ``base = m*H + H - 1``): M polyphase branch dot-products (branch p = prototype phase
    ``coefficients[p::M]`` over samples ``x[base - p - t*M]``, zero history before the
    stream), then an M-point DFT with the gateware's quantized Q1.(W-1) twiddles
    (kernel ``exp(+2j*pi*k*p/M)``: channel k centered at ``+k/M`` of the input rate).
    Products/accumulations are exact; a single round-half-up + saturate by
    ``2*(data_width - 1)`` bits (coefficient + twiddle fractional bits) at the output.
    In 2x mode, odd channels are negated on alternating frames to remove the half-frame DFT
    phase rotation. Returns frame-major channel samples.
    """
    M     = n_channels
    if oversampling not in (1, 2):
        raise ValueError("oversampling must be 1 or 2")
    H     = M//oversampling
    T     = len(coefficients)//M
    xi    = np.asarray(i, np.int64)
    xq    = np.asarray(q, np.int64)
    h     = np.asarray(coefficients, np.int64)
    scale = (1 << (data_width - 1)) - 1
    tw_c  = np.array([int(round(math.cos(2*math.pi*j/M)*scale)) for j in range(M)], np.int64)
    tw_s  = np.array([int(round(math.sin(2*math.pi*j/M)*scale)) for j in range(M)], np.int64)
    shift = 2*(data_width - 1)
    out_i, out_q = [], []
    for m in range(len(xi)//H):
        base = m*H + H - 1
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
            yi = int(np.sum(ui*c) - np.sum(uq*s))
            yq = int(np.sum(ui*s) + np.sum(uq*c))
            if oversampling == 2 and (m & 1) and (k & 1):
                yi, yq = -yi, -yq
            out_i.append(int(np_scaled(yi, shift, data_width)))
            out_q.append(int(np_scaled(yq, shift, data_width)))
    return np.array(out_i, np.int64), np.array(out_q, np.int64)

def pfb_channelizer_fft_model(i, q, coefficients, n_channels, data_width=16, oversampling=1):
    """Bit-exact reference for the PFB channelizer's radix-2 FFT architecture.

    The polyphase FIR is identical to :func:`pfb_channelizer_model`. Its full-precision
    branch sums feed a radix-2 DIF transform; non-trivial twiddle products round back to the
    branch accumulator's Q scale after each rank, and natural channel order is recovered from
    the bit-reversed DIF state before the final coefficient-scale round/saturate.
    """
    M     = n_channels
    if oversampling not in (1, 2):
        raise ValueError("oversampling must be 1 or 2")
    H     = M//oversampling
    T     = len(coefficients)//M
    bits  = M.bit_length() - 1
    xi    = np.asarray(i, np.int64)
    xq    = np.asarray(q, np.int64)
    h     = np.asarray(coefficients, np.int64)
    scale = (1 << (data_width - 1)) - 1
    tw_c  = np.array([int(round(math.cos(2*math.pi*j/M)*scale)) for j in range(M)], np.int64)
    tw_s  = np.array([int(round(math.sin(2*math.pi*j/M)*scale)) for j in range(M)], np.int64)
    out_i, out_q = [], []
    for m in range(len(xi)//H):
        base = m*H + H - 1
        fi, fq = [0]*M, [0]*M
        for p in range(M):
            for t in range(T):
                n = base - p - t*M
                if n >= 0:
                    fi[p] += int(h[p + t*M])*int(xi[n])
                    fq[p] += int(h[p + t*M])*int(xq[n])
        for s in range(bits):
            D = M >> (s + 1)
            for group in range(0, M, 2*D):
                for p in range(D):
                    a, b = group + p, group + p + D
                    ar, aq, br, bq = fi[a], fq[a], fi[b], fq[b]
                    fi[a], fq[a] = ar + br, aq + bq
                    dr, dq = ar - br, aq - bq
                    if p == 0:
                        fi[b], fq[b] = dr, dq
                    else:
                        j = p << s
                        fi[b] = int(np_rounded(dr*int(tw_c[j]) - dq*int(tw_s[j]),
                                               data_width - 1))
                        fq[b] = int(np_rounded(dr*int(tw_s[j]) + dq*int(tw_c[j]),
                                               data_width - 1))
        for k in range(M):
            r = _bit_reverse(k, bits)
            yi, yq = fi[r], fq[r]
            if oversampling == 2 and (m & 1) and (k & 1):
                yi, yq = -yi, -yq
            out_i.append(int(np_scaled(yi, data_width - 1, data_width)))
            out_q.append(int(np_scaled(yq, data_width - 1, data_width)))
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

def dc_blocker_model(x, pole_shift=5, data_width=16, precision_bits=0):
    """Reference for litedsp.filter.dc_blocker.DCBlocker (one channel).

    ``precision_bits = p > 0`` mirrors the high-precision mode: the recursion runs p bits
    wider with an away-from-zero-rounded leak (no truncation deadband) and the output is
    requantized to ``data_width`` with first-order error feedback (DC-free quantization).
    """
    x = np.asarray(x, np.int64)
    y = np.zeros(len(x), np.int64)
    x_prev = 0
    if precision_bits == 0:
        y_prev = 0
        for n in range(len(x)):
            yv = np_saturated(x[n] - x_prev + y_prev - (y_prev >> pole_shift), data_width)
            y[n]   = yv
            x_prev = x[n]
            y_prev = yv
        return y
    p, ps = precision_bits, pole_shift
    W      = data_width + p
    y_wide = 0                                  # Recursive state, p fractional bits.
    e      = 0                                  # Error-feedback state.
    for n in range(len(x)):
        xn   = int(x[n])
        leak = (y_wide >> ps) if y_wide < 0 else ((y_wide + (1 << ps) - 1) >> ps)
        y_wide = int(np_saturated(np.int64(((xn - x_prev) << p) + y_wide - leak), W))
        s      = y_wide + e
        q      = (s + (1 << (p - 1))) >> p      # Round half up (litedsp.common.rounded).
        e      = s - (q << p)
        y[n]   = np_saturated(np.int64(q), data_width)
        x_prev = xn
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
    mu_shift=20, cma_egain=0, mode=0, cma_r2=0, dd_level=0, train=1,
    adaptation_delay=1):
    """Reference for litedsp.filter.equalizer.LiteDSPLMSEqualizer (bit-exact, all modes).

    Per accepted sample (the gateware gates everything on xfer, so the sequence is
    handshake-invariant): shift the input window, filter with the current weights, form the
    mode-selected error (0 = trained ``e = d - y``, 1 = CMA ``e = y*(R2 - |y|^2)`` with the
    gateware's frac-(W-1-cma_egain) rescale/round/saturate, 2 = DD nearest-QPSK at ``dd_level``), then
    apply a prior sample's error on its window snapshot (delayed LMS), gated by
    ``train``. ``mode`` and ``train`` accept scalars or per-sample sequences (runtime
    switching). ``adaptation_delay`` selects the one-sample classic, eight-sample pipelined, or
    nine-sample update-pipelined distance. Returns (i, q) output arrays.
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
    errors = []                                         # Pending (e, window) updates.
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
        if train[k] and len(errors) >= adaptation_delay:
            pei, peq, pxr, pxi = errors[-adaptation_delay]
            for t in range(n_taps):
                wr[t] = int(np_saturated(np.int64(wr[t] + ((pei*pxr[t] + peq*pxi[t]) >> mu_shift)), ww))
                wi[t] = int(np_saturated(np.int64(wi[t] + ((peq*pxr[t] - pei*pxi[t]) >> mu_shift)), ww))
        errors.append((e_i, e_q, list(xr), list(xi)))
        out_i[k], out_q[k] = yi, yq
    return out_i, out_q

# ISqrt --------------------------------------------------------------------------------------------

def isqrt_model(x):
    """Reference for litedsp.numeric.ISqrt (floor integer square root)."""
    return np.array([int(np.floor(np.sqrt(int(v)))) for v in np.asarray(x, np.int64)], np.int64)

# Log2 ---------------------------------------------------------------------------------------------

def log2_model(x, in_width=32, frac_bits=8, lut=False):
    """Reference for litedsp.level.logdb.Log2 (linear-mantissa approximation, or the ROM-
    refined mantissa ``round(log2(1 + m/2**F)*2**F)`` with ``lut=True``)."""
    out = []
    for v in np.asarray(x, np.int64):
        v = int(v)
        if v <= 0:
            out.append(0)
            continue
        msb     = v.bit_length() - 1
        shifted = v << (in_width - 1 - msb)
        mant    = (shifted >> (in_width - 1 - frac_bits)) & ((1 << frac_bits) - 1)
        if lut:
            mant = int(round(math.log2(1 + mant/(1 << frac_bits))*(1 << frac_bits)))
        out.append((msb << frac_bits) | mant)
    return np.array(out, np.int64)

def exp2_model(v, in_width=16, frac_bits=8, out_frac=20, out_width=25):
    """Bit-exact reference for litedsp.level.logdb.LiteDSPExp2: unsigned 2**v in Q.out_frac,
    ROM mantissa ``round(2**(f/2**F)*2**out_frac)`` shifted by the integer part (left:
    saturating, right: round-half-up), per sample."""
    F, OF, OW = frac_bits, out_frac, out_width
    LMAX, RMAX = OW - OF, OF + 2
    out = []
    for x in np.asarray(v, np.int64):
        x = int(x)
        i, f = x >> F, x & ((1 << F) - 1)
        rom  = int(round(2**(f/(1 << F))*(1 << OF)))
        if i < 0:
            r = min(-i, RMAX)
            out.append((rom + ((1 << (r - 1)) if r else 0)) >> r)
        elif i > LMAX or (rom << i) >= (1 << OW):
            out.append((1 << OW) - 1)
        else:
            out.append(rom << i)
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

def agc_model(i, q, target, data_width=16, gain_frac=8, mu=8, gain_max=None, beta_shift=2,
              delayed_feedback=False, feedback_delay=None):
    """Reference for litedsp.level.agc.LiteDSPAGC (bit-exact).

    Per accepted sample: apply the current gain (round-half-up + saturate), measure the output
    magnitude (alpha-max-beta-min), then integrate ``gain += (target - |y|) >> mu`` clamped to
    ``[0, gain_max]``. With ``delayed_feedback=True`` the observation is applied on the next
    accepted sample; ``feedback_delay`` explicitly selects 0, 1, or 2 samples and overrides the
    compatibility switch. The gateware loop pauses with the stream, so every sequence is
    handshake-invariant and this model holds under backpressure too. Returns (i, q).
    """
    gain_width = gain_frac + data_width
    if gain_max is None:
        gain_max = (1 << gain_width) - 1
    gain = 1 << gain_frac                               # Start at 1.0 (Q?.gain_frac).
    if feedback_delay is None:
        feedback_delay = int(delayed_feedback)
    pending_mag = []
    out_i = np.zeros(len(i), np.int64)
    out_q = np.zeros(len(q), np.int64)
    for n, (xi, xq) in enumerate(zip(np.asarray(i, np.int64), np.asarray(q, np.int64))):
        yi = int(np_scaled(int(xi)*gain, gain_frac, data_width))
        yq = int(np_scaled(int(xq)*gain, gain_frac, data_width))
        ai, aq   = abs(yi), abs(yq)
        mag      = (ai + (aq >> beta_shift)) if ai > aq else (aq + (ai >> beta_shift))
        if feedback_delay:
            if len(pending_mag) >= feedback_delay:
                gain = min(max(gain + ((target - pending_mag[-feedback_delay]) >> mu), 0), gain_max)
            pending_mag.append(mag)
        else:
            gain = min(max(gain + ((target - mag) >> mu), 0), gain_max)  # >> is arithmetic.
        out_i[n] = yi
        out_q[n] = yq
    return out_i, out_q

# DPD Actuator -------------------------------------------------------------------------------------

def dpd_mag_model(i, q):
    """Two-region alpha-max-beta-min magnitude of litedsp.level.dpd (max(hi, hi - hi/8 + lo/2))."""
    ai = np.abs(np.asarray(i, np.int64))
    aq = np.abs(np.asarray(q, np.int64))
    hi = np.maximum(ai, aq)
    lo = np.minimum(ai, aq)
    return np.maximum(hi, hi - (hi >> 3) + (lo >> 1))

def dpd_lut_index_model(i, q, lut_depth=64, data_width=16):
    """LUT bin of each sample: top bits of the magnitude estimate, clamped to the last entry."""
    shift = data_width - 1 - int(np.log2(lut_depth))
    return np.minimum(dpd_mag_model(i, q) >> shift, lut_depth - 1)

def dpd_identity_luts(n_taps=3, lut_depth=64, coeff_frac=14):
    """Reset LUT contents of litedsp.level.dpd (tap 0 = 1.0 + 0j, memory taps = 0)."""
    return [(np.full(lut_depth, (1 << coeff_frac) if m == 0 else 0, np.int64),
             np.zeros(lut_depth, np.int64)) for m in range(n_taps)]

def dpd_model(i, q, luts, data_width=16, coeff_frac=14):
    """Reference for litedsp.level.dpd.LiteDSPDPD (bit-exact).

    ``y[n] = sum_m x[n-m] * G_m(|x[n-m]|)``: per tap, the delayed sample is multiplied by the
    complex LUT gain selected by its own magnitude bin; products are kept full width and a
    single round-half-up + saturate by ``coeff_frac`` produces the output. ``luts`` is a
    sequence of ``(lut_i, lut_q)`` integer arrays (signed Q2.coeff_frac), one per tap; the
    delay line starts at zero (matching the hardware reset). Returns (i, q).
    """
    i = np.asarray(i, np.int64)
    q = np.asarray(q, np.int64)
    acc_i = np.zeros(len(i), np.int64)
    acc_q = np.zeros(len(q), np.int64)
    for m, (lut_i, lut_q) in enumerate(luts):
        lut_i = np.asarray(lut_i, np.int64)
        lut_q = np.asarray(lut_q, np.int64)
        xi = np.concatenate([np.zeros(m, np.int64), i[:len(i) - m]]) if m else i
        xq = np.concatenate([np.zeros(m, np.int64), q[:len(q) - m]]) if m else q
        idx = dpd_lut_index_model(xi, xq, len(lut_i), data_width)
        acc_i += xi*lut_i[idx] - xq*lut_q[idx]
        acc_q += xi*lut_q[idx] + xq*lut_i[idx]
    return (np_scaled(acc_i, coeff_frac, data_width),
            np_scaled(acc_q, coeff_frac, data_width))

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
    """Reference for litedsp.level.peak.LiteDSPEnvelopeDetector.

    Per sample: ``env += (|x| - env) >> attack`` when rising, ``>> release`` when falling
    (arithmetic shifts, matching the signed Migen shifts), with |x| the alpha-max-beta-min
    magnitude. Hardware state advances on accepted stream transfers, so valid/ready timing
    does not enter the model.
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
# Conventional-basis RS over GF(2^8), plus the CCSDS 131.0-B-5 dual-basis profile.

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

def rs_generator(n_parity, fcr=0, prim=1, poly=RS_GF_POLY):
    """RS generator polynomial with roots alpha**((fcr+i)*prim), ascending coefficients."""
    exp, _ = gf_tables(poly)
    g = [1]
    for i in range(n_parity):
        root = exp[((fcr + i)*prim) % 255]
        ng = [0]*(len(g) + 1)
        for j, c in enumerate(g):
            ng[j]     ^= gf_mul(c, root, poly)
            ng[j + 1] ^= c
        g = ng
    return g

def rs_encode_model(message, n=255, k=223, poly=RS_GF_POLY, fcr=0, prim=1):
    """Reference for litedsp.comm.rs.LiteDSPRSEncoder: k message bytes -> n-byte codeword.

    Systematic LFSR division by g(x); the 2t parity bytes follow the message, highest-degree
    coefficient first (mirrors the hardware drain order).
    """
    assert len(message) == k
    n_par = n - k
    g = rs_generator(n_par, fcr=fcr, prim=prim, poly=poly)
    p = [0]*n_par                       # p[i] = coefficient of x^i of the running remainder.
    for byte in message:
        fb = int(byte) ^ p[-1]
        p  = [gf_mul(fb, g[0], poly)] + [
            p[i - 1] ^ gf_mul(fb, g[i], poly) for i in range(1, n_par)]
    return [int(byte) for byte in message] + p[::-1]

def rs_decode_model(codeword, n=255, k=223, poly=RS_GF_POLY, fcr=0, prim=1):
    """Reference for litedsp.comm.rs.LiteDSPRSDecoder; returns ``(message, corrected, uncorrectable)``.

    Full hard-decision decode (syndromes, Berlekamp-Massey, Chien, Forney), mirroring the
    hardware exactly — including the degree-t truncation of the BM register files and the
    root-count/locator-degree consistency check — so message bytes *and* status match
    bit-for-bit. An uncorrectable block returns the received message bytes unmodified with
    ``corrected = 0``.
    """
    exp, log = gf_tables(poly)
    n_par = n - k
    t     = n_par//2
    rx    = [int(byte) for byte in codeword]
    assert len(rx) == n

    # Syndromes S_i = r(alpha**((fcr+i)*prim)).
    synd = [0]*n_par
    for byte in rx:
        synd = [gf_mul(synd[i], exp[((fcr + i)*prim) % 255], poly) ^ byte
                for i in range(n_par)]
    if not any(synd):
        return rx[:k], 0, False

    # Berlekamp-Massey, register files truncated at degree t (as in hardware).
    lam = [1] + [0]*t
    B   = [1] + [0]*t
    L, m, b = 0, 1, 1
    for r in range(n_par):
        d = 0
        for j in range(min(r, t) + 1):
            d ^= gf_mul(lam[j], synd[r - j], poly)
        if d == 0:
            m += 1
            continue
        coef = gf_mul(d, exp[255 - log[b]], poly)    # d/b via the log/antilog tables.
        swap = 2*L <= r
        old  = list(lam)
        for j in range(t + 1):
            lam[j] ^= gf_mul(coef, B[j - m], poly) if j >= m else 0
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
            omg[j] ^= gf_mul(synd[l], lam[j - l], poly)

    # Scan coefficient position i at x = alpha**(-prim*i). The Forney numerator carries
    # x**fcr, which is unity for the default code and restores the CCSDS fcr weighting.
    q = list(lam)
    o = list(omg)
    x_fcr = 1
    x_fcr_step = exp[(-prim*fcr) % 255]
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
                numerator = gf_mul(om_val, x_fcr, poly)
                roots.append((n - 1 - i,
                    gf_mul(numerator, exp[255 - log[odd]], poly)))
        q = [gf_mul(q[j], exp[(-prim*j) % 255], poly) for j in range(t + 1)]
        o = [gf_mul(o[j], exp[(-prim*j) % 255], poly) for j in range(t)]
        x_fcr = gf_mul(x_fcr, x_fcr_step, poly)

    if anomaly or len(roots) != L:
        return rx[:k], 0, True
    for idx, mag in roots:
        rx[idx] ^= mag
    return rx[:k], len(roots), False

CCSDS_GF_POLY = 0x187
CCSDS_FCR     = 112
CCSDS_PRIM    = 11

def ccsds_basis_tables():
    """Conventional-alpha <-> CCSDS Berlekamp dual-basis symbol maps (Annex F)."""
    tal = (0x8d, 0xef, 0xec, 0x86, 0xfa, 0x99, 0xaf, 0x7b)
    to_dual = [0]*256
    to_conventional = [0]*256
    for value in range(256):
        mapped = 0
        for out_bit in range(8):
            for in_bit in range(8):
                if value & (1 << in_bit):
                    mapped ^= tal[7 - in_bit] & (1 << out_bit)
        to_dual[value] = mapped
        to_conventional[mapped] = value
    return to_dual, to_conventional

CCSDS_TO_DUAL, CCSDS_TO_CONVENTIONAL = ccsds_basis_tables()

def ccsds_rs_encode_model(message):
    """CCSDS RS(255,223): dual-basis message bytes to a dual-basis systematic codeword."""
    conventional = [CCSDS_TO_CONVENTIONAL[int(byte)] for byte in message]
    codeword = rs_encode_model(conventional, poly=CCSDS_GF_POLY,
        fcr=CCSDS_FCR, prim=CCSDS_PRIM)
    return [CCSDS_TO_DUAL[byte] for byte in codeword]

def ccsds_rs_decode_model(codeword):
    """Decode a CCSDS dual-basis RS(255,223) codeword."""
    conventional = [CCSDS_TO_CONVENTIONAL[int(byte)] for byte in codeword]
    message, corrected, uncorrectable = rs_decode_model(conventional, poly=CCSDS_GF_POLY,
        fcr=CCSDS_FCR, prim=CCSDS_PRIM)
    return [CCSDS_TO_DUAL[byte] for byte in message], corrected, uncorrectable

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

# Timestamps ---------------------------------------------------------------------------------------

def timestamper_model(times, first=None, last=None):
    """Reference for litedsp.stream.timestamp.LiteDSPTimestamper (timestamp tags only).

    ``times[k]`` is the TimeCore count when sample ``k`` is accepted; ``first``/``last`` are
    its framing flags (None = unframed). Returns the per-sample ``timestamp`` tag: the time of
    the most recent frame ``first`` (held over the frame), or the sample's own time when
    outside a frame (unframed streams tag continuously). The payload passes through untouched.
    """
    n     = len(times)
    first = [0]*n if first is None else first
    last  = [0]*n if last  is None else last
    tags, stamp, in_frame = [], 0, False
    for t, f, l in zip(times, first, last):
        if f or not in_frame:
            stamp = t
        tags.append(stamp)
        in_frame = bool(not l and (f or in_frame))
    return tags

def time_untagger_model(i, q):
    """Reference for litedsp.stream.timestamp.LiteDSPTimeUntagger (identity on the payload)."""
    return np.asarray(i, np.int64), np.asarray(q, np.int64)

# OFDM framing -------------------------------------------------------------------------------------

def cp_insert_model(i, q, fft_size=64, cp_len=16):
    """Insert each complete OFDM symbol's tail before its payload."""
    out_i, out_q = [], []
    for start in range(0, min(len(i), len(q)), fft_size):
        frame_i = list(i[start:start + fft_size])
        frame_q = list(q[start:start + fft_size])
        if len(frame_i) != fft_size or len(frame_q) != fft_size:
            break
        out_i += frame_i[-cp_len:] + frame_i
        out_q += frame_q[-cp_len:] + frame_q
    return np.asarray(out_i, dtype=np.int64), np.asarray(out_q, dtype=np.int64)

def cp_remove_model(i, q, fft_size=64, cp_len=16):
    """Drop the prefix from each complete CP + OFDM-symbol frame."""
    frame_size = fft_size + cp_len
    out_i, out_q = [], []
    for start in range(0, min(len(i), len(q)), frame_size):
        frame_i = list(i[start:start + frame_size])
        frame_q = list(q[start:start + frame_size])
        if len(frame_i) != frame_size or len(frame_q) != frame_size:
            break
        out_i += frame_i[cp_len:]
        out_q += frame_q[cp_len:]
    return np.asarray(out_i, dtype=np.int64), np.asarray(out_q, dtype=np.int64)

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

def parallel_fft_model(frame_i, frame_q, data_width=16, twiddle_width=16):
    """Bit-exact reference for litedsp.analysis.fft_parallel.LiteDSPParallelFFT (P=2).

    The parallel FFT is the serial radix-2 SDF "scaled" schedule regrouped (first DIF
    butterfly rank, then two independent N/2 serial cascades), with every rounding at the
    same position — so its flattened lane stream is, by construction, :func:`fft_fixed_model`
    exactly. Returns ``(i, q)`` int arrays of shape ``(N//2, 2)``: row ``m`` is output beat
    ``m``, whose lanes carry the serial FFT's bit-reversed outputs ``2m`` and ``2m + 1``,
    i.e. bins ``X[r]`` and ``X[r + N/2]`` with ``r = bit_reverse(m, log2(N/2))``.
    """
    fi, fq = fft_fixed_model(frame_i, frame_q, data_width, twiddle_width)
    return fi.reshape(-1, 2), fq.reshape(-1, 2)

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

# Block Interleaver / Deinterleaver ------------------------------------------------------------------

def block_interleave_model(data, rows=5, cols=255):
    """Reference for litedsp.comm.interleaver.LiteDSPBlockInterleaver: row-wise in, column-wise out.

    Per rows*cols block: the symbols are written into a rows x cols matrix row-wise (CCSDS:
    one RS codeword per row) and read out column-wise (the flattened transpose). Trailing
    symbols that do not complete a block are dropped (still buffered in hardware).
    """
    n   = rows*cols
    out = []
    for b in range(len(data)//n):
        block = np.asarray(data[b*n:(b + 1)*n]).reshape(rows, cols)
        out  += [int(x) for x in block.T.reshape(-1)]
    return out

def block_deinterleave_model(data, rows=5, cols=255):
    """Reference for litedsp.comm.interleaver.LiteDSPBlockDeinterleaver (the exact inverse).

    Per rows*cols block: the symbols are written into a cols x rows matrix row-wise (arrival =
    channel order = column-wise in the interleaver's matrix) and read out column-wise,
    restoring the original order. Trailing symbols that do not complete a block are dropped.
    """
    n   = rows*cols
    out = []
    for b in range(len(data)//n):
        block = np.asarray(data[b*n:(b + 1)*n]).reshape(cols, rows)
        out  += [int(x) for x in block.T.reshape(-1)]
    return out

# LDPC (802.11n rate-1/2, n=648, z=27) ---------------------------------------------------------------

# IEEE 802.11-2012 Annex F, Table F-1 (n = 648, rate 1/2, z = 27) base matrix — deliberately
# duplicated from litedsp.comm.ldpc (models stay independent of the gateware): -1 = zero
# 27x27 block, s >= 0 = identity right-cyclic-shifted by s (block row r: one at column
# (r + s) mod 27). Info blocks 0..11, dual-diagonal parity blocks 12..23.
LDPC_BASE = [
    [ 0, -1, -1, -1,  0,  0, -1, -1,  0, -1, -1,  0,  1,  0, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
    [22,  0, -1, -1, 17, -1,  0,  0, 12, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1, -1, -1, -1, -1],
    [ 6, -1,  0, -1, 10, -1, -1, -1, 24, -1,  0, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1, -1, -1, -1],
    [ 2, -1, -1,  0, 20, -1, -1, -1, 25,  0, -1, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1, -1, -1],
    [23, -1, -1, -1,  3, -1, -1, -1,  0, -1,  9, 11, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1, -1],
    [24, -1, 23,  1, 17, -1,  3, -1, 10, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1, -1],
    [25, -1, -1, -1,  8, -1, -1, -1,  7, 18, -1, -1,  0, -1, -1, -1, -1, -1,  0,  0, -1, -1, -1, -1],
    [13, 24, -1, -1,  0, -1,  8, -1,  6, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0, -1, -1, -1],
    [ 7, 20, -1, 16, 22, 10, -1, -1, 23, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0, -1, -1],
    [11, -1, -1, -1, 19, -1, -1, -1, 13, -1,  3, 17, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0, -1],
    [25, -1,  8, -1, 23, 18, -1, 14,  9, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0,  0],
    [ 3, -1, -1, -1, 16, -1, -1,  2, 25,  5, -1, -1,  1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1,  0],
]

LDPC_Z = 27
LDPC_N = 648
LDPC_K = 324

def ldpc_expand_h():
    """Dense 324 x 648 binary H expanded from the base matrix (parity-check reference)."""
    z, mb, nb = LDPC_Z, len(LDPC_BASE), len(LDPC_BASE[0])
    H = np.zeros((mb*z, nb*z), dtype=np.uint8)
    for i in range(mb):
        for b in range(nb):
            s = LDPC_BASE[i][b]
            if s < 0:
                continue
            for r in range(z):
                H[i*z + r, b*z + (r + s) % z] = 1
    return H

def ldpc_check_parity(codeword):
    """True iff H*c^T = 0 over GF(2) (the mathematical validity check for a codeword)."""
    c = np.asarray(codeword, dtype=np.uint8)
    return not np.any((ldpc_expand_h() @ c) % 2)

def ldpc_layer_edges():
    """Per base row: the (col_block, shift) nonzero entries in ascending column order.

    This is the decoder schedule: layer i processes its edges in this order, and check row
    j of layer i touches variable ``b*z + (s + j) % z`` for each edge (b, s).
    """
    nb = len(LDPC_BASE[0])
    return [[(b, s) for b, s in ((b, row[b]) for b in range(nb)) if s >= 0]
            for row in LDPC_BASE]

def ldpc_encode_model(message):
    """Reference for litedsp.comm.ldpc.LiteDSPLDPCEncoder: 324 message bits -> 648-bit codeword.

    Back-substitution over the quasi-cyclic dual-diagonal parity structure, mirroring the
    hardware: lambda_i = sum_b P(s_ib) msg_b, p0 = sum_i lambda_i (column-12 shifts (1, 0, 1)
    telescope to P(0)), p1 = lambda_0 + P(1) p0, p_{r+1} = p_r + lambda_r (+ p0 at r = 6);
    row 11 closes by construction (asserted). Systematic: codeword = [message | parity].
    """
    z, mb = LDPC_Z, len(LDPC_BASE)
    msg = np.asarray(message, dtype=np.uint8)
    assert msg.shape == (LDPC_K,)
    blocks = msg.reshape(mb, z)

    def rot(x, s):  # (P(s) x)[r] = x[(r + s) % z].
        return np.roll(x, -s)

    lam = np.zeros((mb, z), dtype=np.uint8)
    for i in range(mb):
        for b in range(mb):  # Info block columns 0..11.
            s = LDPC_BASE[i][b]
            if s >= 0:
                lam[i] ^= rot(blocks[b], s)
    p = np.zeros((mb, z), dtype=np.uint8)
    p[0] = lam.sum(axis=0) % 2
    p[1] = lam[0] ^ rot(p[0], 1)
    for r in range(1, mb - 1):
        p[r + 1] = p[r] ^ lam[r]
        if r == 6:
            p[r + 1] ^= p[0]
    assert not np.any(lam[mb - 1] ^ rot(p[0], 1) ^ p[mb - 1])  # Row 11 closes.
    return [int(b) for b in np.concatenate([msg, p.reshape(-1)])]

def ldpc_decode_model(llrs, llr_bits=4, max_iters=8):
    """Reference for litedsp.comm.ldpc.LiteDSPLDPCDecoder; returns ``(bits, iterations, parity_ok)``.

    Row-layered normalized min-sum mirroring the hardware exactly: layers = base rows in
    order, z serial check rows per layer, edges in ascending column order, compressed check
    messages (min1/min2/index/signs, magnitudes stored normalized by 0.75 = x - (x >> 2)),
    Q = APP - R_old kept at full precision for the write-back with |Q| clamped to
    2**llr_bits - 1 only on the check-node input, APP saturated to ±(2**(llr_bits+1) - 1),
    early termination on an iteration whose on-the-fly syndrome (parity of Q signs) is clean
    for every check row. Positive LLR = bit 0; returns the k hard-decision message bits.
    """
    z, mb  = LDPC_Z, len(LDPC_BASE)
    qmax   = (1 << llr_bits) - 1
    appmax = (1 << (llr_bits + 1)) - 1
    app = np.clip(np.asarray(llrs, dtype=np.int64), -appmax, appmax).copy()
    assert app.shape == (LDPC_N,)
    edges = ldpc_layer_edges()
    msgs  = {}  # (layer, row) -> (min1n, min2n, idx, signs): the compressed check message.
    for it in range(1, max_iters + 1):
        all_sat = True
        for i in range(mb):
            deg = len(edges[i])
            for j in range(z):
                addrs = [b*z + (s + j) % z for b, s in edges[i]]
                # R_old from the compressed message (0 on the first iteration).
                if (i, j) in msgs:
                    om1, om2, oidx, osg = msgs[(i, j)]
                    otot  = 0
                    for sg in osg:
                        otot ^= sg
                    r_old = [(om2 if e == oidx else om1)*(1 - 2*(otot ^ osg[e]))
                             for e in range(deg)]
                else:
                    r_old = [0]*deg
                # Q = APP - R_old (full precision); check node sees |Q| clamped to qmax.
                q = []
                signs = []
                m1, m2, idx = qmax, qmax, 0
                for e in range(deg):
                    qe = int(app[addrs[e]]) - r_old[e]
                    q.append(qe)
                    signs.append(1 if qe < 0 else 0)
                    mag = min(-qe if qe < 0 else qe, qmax)
                    if mag < m1:
                        m2, m1, idx = m1, mag, e
                    elif mag < m2:
                        m2 = mag
                tot = 0
                for sg in signs:
                    tot ^= sg
                if tot:
                    all_sat = False
                # Normalize once at store time; write back APP = sat(Q + R_new).
                m1n, m2n = m1 - (m1 >> 2), m2 - (m2 >> 2)
                msgs[(i, j)] = (m1n, m2n, idx, signs)
                for e in range(deg):
                    r_new = (m2n if e == idx else m1n)*(1 - 2*(tot ^ signs[e]))
                    app[addrs[e]] = max(-appmax, min(appmax, q[e] + r_new))
        if all_sat:
            return [int(b) for b in (app[:LDPC_K] < 0).astype(np.uint8)], it, True
    return [int(b) for b in (app[:LDPC_K] < 0).astype(np.uint8)], max_iters, False

# Motor Control: Reference-Frame Transforms --------------------------------------------------------

CLARKE_C_1_3   = int(round((1/3)*(1 << 15)))             # Q1.15 transform constants (as RTL).
CLARKE_C_1_SQ3 = int(round((1/math.sqrt(3))*(1 << 15)))
CLARKE_C_SQ3_2 = int(round((math.sqrt(3)/2)*(1 << 15)))

def clarke_model(a, b, c, data_width=16, three_wire=False):
    """Bit-exact reference for litedsp.motor.transforms.LiteDSPClarke. Returns (alpha, beta)."""
    a, b, c = (np.asarray(v, np.int64) for v in (a, b, c))
    if three_wire:
        alpha = np.array(a, np.int64)
        beta  = np_scaled((a + 2*b)*CLARKE_C_1_SQ3, 15, data_width)
    else:
        alpha = np_scaled((2*a - b - c)*CLARKE_C_1_3, 15, data_width)
        beta  = np_scaled((b - c)*CLARKE_C_1_SQ3, 15, data_width)
    return alpha, beta

def inverse_clarke_model(alpha, beta, data_width=16):
    """Bit-exact reference for litedsp.motor.transforms.LiteDSPInverseClarke. Returns (a, b, c)."""
    alpha, beta = np.asarray(alpha, np.int64), np.asarray(beta, np.int64)
    kb   = beta*CLARKE_C_SQ3_2                # sqrt(3)/2 * beta, Q.15 domain.
    half = alpha*(1 << 14)                    # alpha/2, Q.15 domain.
    return (np.array(alpha, np.int64),
            np_scaled(kb - half, 15, data_width),
            np_scaled(-kb - half, 15, data_width))

def cordic_rotation_model(x, y, z, data_width=16, angle_width=16, stages=None):
    """Bit-exact reference for litedsp.generation.cordic.LiteDSPCORDIC rotation (one vector).

    Mirrors :func:`cordic_vectoring_model` for the rotation mode: pre-rotation by pi when
    |z| > pi/2, per-stage floor shifts, the angle_width-quantized atan LUT, and the final
    Q1.15 1/K gain compensation with round + saturate. Returns ``(x, y)``.
    """
    if stages is None:
        stages = data_width
    W, Wz = data_width + 2, angle_width + 2
    PI    = 1 << (angle_width - 1)
    atan  = [int(round(math.atan(2.0**(-i))/(2*math.pi)*(1 << angle_width))) for i in range(stages)]
    gain  = 1.0
    for i in range(stages):
        gain *= math.sqrt(1 + 2.0**(-2*i))
    kinv  = int(round((1/gain)*((1 << 15) - 1)))
    wx, wz, wa = _wrapper(W), _wrapper(Wz), _wrapper(angle_width)
    x, y, z = int(x), int(y), wa(int(z))
    # Pre-rotation into the convergence region (|z| > pi/2 -> rotate by pi first).
    flip = ((z >> (angle_width - 1)) & 1) ^ ((z >> (angle_width - 2)) & 1)
    if flip:
        x, y, z = -x, -y, wa(z + PI)
    x, y, z = wx(x), wx(y), wz(z)
    # Iterations (d = sign(z): drive z -> 0).
    for i in range(stages):
        sh_x, sh_y = x >> i, y >> i
        if z >= 0:
            x, y, z = wx(x - sh_y), wx(y + sh_x), wz(z - atan[i])
        else:
            x, y, z = wx(x + sh_y), wx(y - sh_x), wz(z + atan[i])
    return (int(np_scaled(np.int64(x*kinv), 15, data_width)),
            int(np_scaled(np.int64(y*kinv), 15, data_width)))

def sincos_model(angle, data_width=16, angle_width=16, lut_depth=1024, method="rom", stages=None):
    """Bit-exact reference for litedsp.motor.transforms.LiteDSPSinCos. Returns (cos, sin)."""
    angle = np.asarray(angle, np.int64)
    if method == "rom":
        addr_bits    = int(round(np.log2(lut_depth)))
        cos_t, sin_t = nco_lut(lut_depth, data_width)
        addr = (angle & ((1 << angle_width) - 1)) >> (angle_width - addr_bits)
        return cos_t[addr], sin_t[addr]
    scale = (1 << (data_width - 1)) - 1
    out   = [cordic_rotation_model(scale, 0, int(z), data_width, angle_width, stages) for z in angle]
    return (np.array([o[0] for o in out], np.int64), np.array([o[1] for o in out], np.int64))

def angle_ramp_model(phase_inc, n, angle_width=16, phase_bits=32):
    """Reference for litedsp.motor.transforms.LiteDSPAngleRamp: n signed angles."""
    mask, wrap = (1 << phase_bits) - 1, _wrapper(angle_width)
    phase, out = 0, []
    for _ in range(n):
        phase = (phase + phase_inc) & mask
        out.append(wrap(phase >> (phase_bits - angle_width)))
    return np.array(out, np.int64)

def park_model(alpha, beta, angle, data_width=16, angle_width=16, lut_depth=1024, method="rom",
    stages=None):
    """Bit-exact reference for litedsp.motor.transforms.LiteDSPPark: (alpha, beta, theta) -> (d, q)."""
    cos, sin = sincos_model(angle, data_width, angle_width, lut_depth, method, stages)
    return mixer_model(alpha, beta, cos, sin, mode="down", data_width=data_width)

def inverse_park_model(d, q, angle, data_width=16, angle_width=16, lut_depth=1024, method="rom",
    stages=None):
    """Bit-exact reference for litedsp.motor.transforms.LiteDSPInversePark: (d, q, theta) -> (alpha, beta)."""
    cos, sin = sincos_model(angle, data_width, angle_width, lut_depth, method, stages)
    return mixer_model(d, q, cos, sin, mode="up", data_width=data_width)

# Motor Control: Regulators ------------------------------------------------------------------------

def _per_sample(v, n):
    """Broadcast a scalar control to ``n`` samples, or pass a per-sample array through."""
    v = np.asarray(v, np.int64)
    return np.full(n, int(v), np.int64) if v.ndim == 0 else v[:n]

def pi_controller_model(y, setpoint, kp, ki, limit=None, feedforward=0, data_width=16,
    gain_width=16, gain_frac=12, anti_windup="conditional", open_loop=0, clear=0):
    """Bit-exact reference for litedsp.motor.transforms.pi.LiteDSPPIController.

    Controls may be scalars or per-sample arrays (the RTL samples them with each accepted
    measurement). Per sample: ``e = setpoint - y``; ``u = clamp(round((kp*e + integral +
    (ff << gain_frac)) / 2**gain_frac), +/-limit)`` using the *old* integral; then
    ``integral = clamp(integral + ki*e, +/-(limit << gain_frac))`` unless conditional
    anti-windup holds it (output clamped in the direction of the error). ``anti_windup="none"``
    wraps the integrator at its ``data_width + gain_frac + 2``-bit width. ``open_loop`` outputs
    the clamped feedforward and zeroes the integrator. Returns the command array.
    """
    y  = np.asarray(y, np.int64)
    n  = len(y)
    if limit is None:
        limit = (1 << (data_width - 1)) - 1
    sp, kp, ki, lim = (_per_sample(v, n) for v in (setpoint, kp, ki, limit))
    ff, ol, cl      = (_per_sample(v, n) for v in (feedforward, open_loop, clear))
    acc_width = data_width + gain_frac + 2
    wrap      = _wrapper(acc_width)
    integral  = 0
    out       = np.zeros(n, np.int64)
    for k in range(n):
        e       = int(sp[k]) - int(y[k])
        u_full  = int(kp[k])*e + integral + (int(ff[k]) << gain_frac)
        u_r     = int(np_rounded(np.int64(u_full), gain_frac))
        u_sel   = int(ff[k]) if ol[k] else u_r
        sat_hi, sat_lo = u_sel > lim[k], u_sel < -lim[k]
        out[k]  = lim[k] if sat_hi else (-lim[k] if sat_lo else u_sel)
        acc_sum = integral + int(ki[k])*e
        lim_acc = int(lim[k]) << gain_frac
        if anti_windup == "none":
            acc_nxt = wrap(acc_sum)
        else:
            acc_nxt = max(-lim_acc, min(lim_acc, acc_sum))
        hold = anti_windup == "conditional" and ((sat_hi and e > 0) or (sat_lo and e < 0))
        if cl[k] or ol[k]:
            integral = 0
        elif not hold:
            integral = acc_nxt
    return out

def dq_decoupling_model(i_d, i_q, speed, l_pu, psi_pu, data_width=16):
    """Bit-exact decoupling feed-forward of LiteDSPDQController: (ff_d, ff_q) per sample."""
    shift = data_width - 1
    i_d, i_q = np.asarray(i_d, np.int64), np.asarray(i_q, np.int64)
    n   = len(i_d)
    w, l, psi = (_per_sample(v, n) for v in (speed, l_pu, psi_pu))
    t_d  = np_scaled(l*i_d, shift, data_width)
    t_q  = np_scaled(l*i_q, shift, data_width)
    flux = np_saturated(t_d + psi, data_width)
    ff_d = -np_scaled(w*t_q, shift, data_width)
    ff_q = np_scaled(w*flux, shift, data_width)
    return ff_d, ff_q

def dq_controller_model(i_d, i_q, setpoint_d, setpoint_q, kp_d, ki_d, kp_q, ki_q, limit=None,
    data_width=16, gain_width=16, gain_frac=12, anti_windup="conditional", open_loop=0,
    voltage_d=0, voltage_q=0, decoupling=False, speed=0, l_pu=0, psi_pu=0):
    """Bit-exact reference for LiteDSPDQController: two PI regulators (+ decoupling). Returns (v_d, v_q)."""
    n = len(i_d)
    if decoupling:
        ff_d, ff_q = dq_decoupling_model(i_d, i_q, speed, l_pu, psi_pu, data_width)
    else:
        ff_d, ff_q = np.zeros(n, np.int64), np.zeros(n, np.int64)
    ol = _per_sample(open_loop, n)
    ff_d = np.where(ol, _per_sample(voltage_d, n), ff_d)
    ff_q = np.where(ol, _per_sample(voltage_q, n), ff_q)
    kw = dict(limit=limit, data_width=data_width, gain_width=gain_width, gain_frac=gain_frac,
        anti_windup=anti_windup, open_loop=ol)
    return (pi_controller_model(i_d, setpoint_d, kp_d, ki_d, feedforward=ff_d, **kw),
            pi_controller_model(i_q, setpoint_q, kp_q, ki_q, feedforward=ff_q, **kw))

def slew_limiter_model(x, rate, data_width=16):
    """Bit-exact reference for litedsp.motor.limiter.LiteDSPSlewLimiter (state = last output)."""
    x    = np.asarray(x, np.int64)
    rate = _per_sample(rate, len(x))
    y, out = 0, np.zeros(len(x), np.int64)
    for k in range(len(x)):
        delta  = int(x[k]) - y
        y     += max(-int(rate[k]), min(int(rate[k]), delta))
        out[k] = y
    return out

# Motor Control: Modulation ------------------------------------------------------------------------

def svpwm_model(alpha, beta, injection=1, data_width=16):
    """Bit-exact reference for litedsp.motor.svpwm.LiteDSPSVPWM. Returns (a, b, c) duties."""
    alpha, beta = np.asarray(alpha, np.int64), np.asarray(beta, np.int64)
    inj  = _per_sample(injection, len(alpha))
    kb   = beta*CLARKE_C_SQ3_2
    half = alpha*(1 << 14)
    a1   = alpha
    b1   = np_rounded(kb - half, 15)                 # data_width + 2 bits, no saturation.
    c1   = np_rounded(-kb - half, 15)
    mx   = np.maximum(np.maximum(a1, b1), c1)
    mn   = np.minimum(np.minimum(a1, b1), c1)
    v0   = np.where(inj != 0, np_rounded(-(mx + mn), 1), 0)
    return tuple(np_saturated(x + v0, data_width) for x in (a1, b1, c1))

def pwm_model(duties, period, dead_time, n_cycles, data_width=16, enable=1, fault=None,
    trigger_count=0, trigger_direction=0):
    """Cycle-exact reference for litedsp.motor.pwm.LiteDSPPWM.

    ``duties`` is the list of ``(a, b, c)`` samples offered back-to-back (the driver always
    holds a valid sample, so one is accepted at every carrier valley; the last one repeats).
    ``fault`` is an optional per-cycle array. Returns per-cycle arrays ``(pwm_h, pwm_l,
    trigger, ready)`` with the gate signals as 3-bit integers (bit k = phase k), mirroring the
    RTL registers from reset (cycle 0 = reset values).
    """
    offset  = 1 << (data_width - 1)
    fault   = np.zeros(n_cycles, np.int64) if fault is None else np.asarray(fault)
    # Registers (reset values).
    count, up = 0, 1                                           # Counting up from reset.
    duty_u    = [offset, offset, offset]
    mul_busy, mul_idx, prod, prod_valid, prod_idx = 0, 0, 0, 0, 0
    cmp_shadow, cmp = [0, 0, 0], [0, 0, 0]
    raw_r, raw_prev, dt_cnt = [0]*3, [0]*3, [0]*3
    pwm_h, pwm_l, trigger, fault_latched = [0]*3, [0]*3, 0, 0
    k_sample = 0
    out_h, out_l, out_t, out_r = [], [], [], []
    for cyc in range(n_cycles):
        # Registered outputs visible this cycle + combinational ready.
        valley = count == 0 and not up
        out_h.append(sum(pwm_h[k] << k for k in range(3)))
        out_l.append(sum(pwm_l[k] << k for k in range(3)))
        out_t.append(trigger)
        out_r.append(int(valley))
        # Combinational.
        sample = duties[min(k_sample, len(duties) - 1)]
        accept = valley
        raw    = [int(count < cmp[k]) for k in range(3)]
        active = int(enable and not fault_latched)
        edge   = [int(raw_r[k] != raw_prev[k]) for k in range(3)]
        dt_nxt = [dead_time if edge[k] else (dt_cnt[k] - 1 if dt_cnt[k] else 0) for k in range(3)]
        # Next state (the trigger below still sees the pre-update `up`).
        up_cur = up
        if up:
            if count >= period:
                up_n, count_n = 0, count - 1
            else:
                up_n, count_n = up, count + 1
        else:
            if valley:
                up_n, count_n = 1, 1
            else:
                up_n, count_n = up, count - 1
        prod_n, prod_valid_n, prod_idx_n = period*duty_u[mul_idx], mul_busy, mul_idx
        if valley:
            cmp = list(cmp_shadow)                                 # Old shadow (same edge).
        if prod_valid:
            cmp_shadow[prod_idx] = int(np_rounded(np.int64(prod), data_width))
        if accept:
            duty_u   = [int(sample[k]) + offset for k in range(3)]
            k_sample += 1
        if accept:
            mul_busy_n, mul_idx_n = 1, 0
        elif mul_busy:
            mul_busy_n, mul_idx_n = (0, mul_idx) if mul_idx == 2 else (1, mul_idx + 1)
        else:
            mul_busy_n, mul_idx_n = 0, mul_idx
        pwm_h   = [int(raw_r[k] and active and dt_nxt[k] == 0) for k in range(3)]
        pwm_l   = [int((not raw_r[k]) and active and dt_nxt[k] == 0) for k in range(3)]
        trigger = int(count == trigger_count and up_cur == trigger_direction)
        raw_prev, raw_r, dt_cnt = list(raw_r), list(raw), list(dt_nxt)
        if fault[cyc]:
            fault_latched = 1
        count, up, mul_busy, mul_idx = count_n, up_n, mul_busy_n, mul_idx_n
        prod, prod_valid, prod_idx = prod_n, prod_valid_n, prod_idx_n
    return (np.array(out_h), np.array(out_l), np.array(out_t), np.array(out_r))

# Bitstream (Sigma-Delta / PDM) Decimator ----------------------------------------------------------

def bitstream_align(r_max, n_stages, diff_delay, data_width):
    """Static alignment shift of LiteDSPBitstreamDecimator (mirrors litedsp.filter.bitstream)."""
    return max(0, (data_width - 1) - _cic_growth(r_max, n_stages, diff_delay))

def bitstream_shift(rate, n_stages, diff_delay, data_width, r_max=None):
    """Rescale shift of LiteDSPBitstreamDecimator at ``rate`` (mirrors litedsp.filter.bitstream)."""
    if r_max is None:
        r_max = rate
    gain_bits = n_stages*math.log2(rate*diff_delay)
    return max(0, int(round(gain_bits)) - (data_width - 1)
        + bitstream_align(r_max, n_stages, diff_delay, data_width))

def bitstream_decimator_model(bits, rate, n_stages=4, diff_delay=1, data_width=24, shift=None,
    r_max=None, staged=False):
    """Bit-exact reference for litedsp.filter.bitstream.LiteDSPBitstreamDecimator.

    ``bits`` are modulator bits (1 -> +1, 0 -> -1); the sinc^N core is the runtime CIC model
    with 2-bit-input register sizing (``2 + growth(r_max)``), followed by the block's static
    alignment shift and saturation. Default ``shift``: the block's reset value for ``rate``.
    ``staged`` models the register-chained architecture's ``n_stages``-sample group delay
    (zeros in the +1/-1 domain, as for LiteDSPCICDecimatorRuntime).
    """
    if r_max is None:
        r_max = rate
    if shift is None:
        shift = bitstream_shift(rate, n_stages, diff_delay, data_width, r_max)
    align = bitstream_align(r_max, n_stages, diff_delay, data_width)
    x = np.where(np.asarray(bits, np.int64) != 0, 1, -1)
    if staged:
        x = np.concatenate([np.zeros(n_stages, np.int64), x])
    y = cic_decimator_model(x, rate, n_stages, diff_delay, data_width, shift=shift,
        wrap_width=2 + _cic_growth(r_max, n_stages, diff_delay))
    return np_saturated(y*(1 << align), data_width)

def sigma_delta_stimulus(x, order=2):
    """Float 2nd-order sigma-delta modulator (test stimulus, not a gateware model): x in
    (-1, 1) at the bit rate -> bits (1 = +1)."""
    e1 = e2 = 0.0
    out = np.zeros(len(x), np.int64)
    for k, v in enumerate(np.asarray(x, float)):
        u = v + (2*e1 - e2 if order == 2 else e1)
        y = 1.0 if u >= 0 else -1.0
        e2, e1 = e1, u - y
        out[k] = int(y > 0)
    return out

# Motor Control: Sensing ---------------------------------------------------------------------------

def sigma_delta_filter_model(bits_channels, rate, threshold, data_width=16, n_stages=3,
    r_max=256, fast_decimation=16, shift=None):
    """Bit-exact reference for litedsp.motor.sense.LiteDSPSigmaDeltaFilter.

    Returns ``(outputs, trips)``: per-channel control-path sample arrays and per-channel
    booleans telling whether the fast path (fixed ``fast_decimation`` sinc^N) ever exceeded
    ``threshold`` in magnitude.
    """
    outputs, trips = [], []
    for bits in bits_channels:
        outputs.append(bitstream_decimator_model(bits, rate, n_stages, 1, data_width, shift, r_max))
        fast = bitstream_decimator_model(bits, fast_decimation, n_stages, 1, data_width)
        trips.append(bool(np.any(np.abs(fast) > threshold)))
    return outputs, trips

def overcurrent_trip_model(a, b, c, threshold):
    """Reference for litedsp.motor.sense.LiteDSPOvercurrentTrip: passthrough + sticky trip
    after each sample (``fault[k]`` = tripped by sample k or earlier)."""
    a, b, c = (np.asarray(v, np.int64) for v in (a, b, c))
    over  = (np.abs(a) > threshold) | (np.abs(b) > threshold) | (np.abs(c) > threshold)
    return a, b, c, np.cumsum(over) > 0

# Motor Control: Position Sensors ------------------------------------------------------------------

def quadrature_decoder_model(a, b, z, counts_per_rev=4096, pole_pairs=1, filter_length=2,
    angle_width=16, scale_frac=16, angle_scale=None, angle_offset=0, invert=False,
    index_enable=False, window=1 << 16, speed_width=16):
    """Cycle-exact reference for litedsp.motor.encoder.LiteDSPQuadratureDecoder.

    ``a``/``b``/``z`` are the pin levels per cycle (as seen by the block, cycle 0 = reset).
    Returns a dict of per-cycle register values (``position``, ``epos``, ``direction``,
    ``error``, ``speed``) and the combinational ``angle`` (what a ``sample`` strobe latches).
    """
    n = len(a)
    if angle_scale is None:
        angle_scale = (1 << (angle_width + scale_frac))//counts_per_rev
    fwd  = {(0b00, 0b01), (0b01, 0b11), (0b11, 0b10), (0b10, 0b00)}
    mask = (1 << angle_width) - 1
    wrap = _wrapper(speed_width)
    pins = [dict(s1=0, s2=0, out=0, cnt=0) for _ in range(3)]
    a_p = b_p = z_p = 0
    position = epos = direction = error = angle_full = win_cnt = delta = speed = 0
    out = {k: np.zeros(n, np.int64) for k in ("position", "epos", "direction", "error", "speed", "angle")}
    for t in range(n):
        out["position"][t], out["epos"][t] = position, epos
        out["direction"][t], out["error"][t], out["speed"][t] = direction, error, speed
        out["angle"][t] = ((angle_full >> scale_frac) + angle_offset) & mask
        # Combinational decode from the filtered pins and their previous values.
        a_f, b_f, z_f = pins[0]["out"], pins[1]["out"], pins[2]["out"]
        prev, cur = a_p | (b_p << 1), a_f | (b_f << 1)
        illegal   = (prev ^ cur) == 0b11
        step      = prev != cur and not illegal
        fwd_match = ((prev, cur) in fwd) ^ bool(invert)
        step_up, step_down = step and fwd_match, step and not fwd_match
        index     = bool(z_f and not z_p and index_enable)
        # Next state: synchronizers + glitch filters.
        for k, pin in enumerate((a, b, z)):
            s = pins[k]
            if filter_length == 1:
                out_n, cnt_n = s["s2"], 0
            elif s["s2"] != s["out"]:
                out_n, cnt_n = (s["s2"], 0) if s["cnt"] == filter_length - 1 else (s["out"], s["cnt"] + 1)
            else:
                out_n, cnt_n = s["out"], 0
            pins[k] = dict(s1=int(pin[t]), s2=s["s1"], out=out_n, cnt=cnt_n)
        a_p, b_p, z_p = a_f, b_f, z_f
        angle_full = epos*angle_scale
        if index:
            position, epos = 0, 0
        elif step_up:
            position  = 0 if position == counts_per_rev - 1 else position + 1
            epos      = epos + pole_pairs
            epos      = epos - counts_per_rev if epos >= counts_per_rev else epos
            direction = 0
        elif step_down:
            position  = counts_per_rev - 1 if position == 0 else position - 1
            epos      = epos - pole_pairs
            epos      = epos + counts_per_rev if epos < 0 else epos
            direction = 1
        if illegal:
            error = 1
        s = 1 if step_up else (-1 if step_down else 0)
        if win_cnt >= window - 1:
            win_cnt, speed, delta = 0, wrap(delta + s), 0
        else:
            win_cnt, delta = win_cnt + 1, wrap(delta + s)
    return out

HALL_SECTORS = {0b001: 0, 0b011: 1, 0b010: 2, 0b110: 3, 0b100: 4, 0b101: 5}

def hall_sector_model(codes, invert=False):
    """Reference for the sector/direction/error decode of LiteDSPHallDecoder: per code in
    the sequence (a new code per entry), returns (sector, direction, error) arrays."""
    sector, direction, error, armed = 0, 0, 0, False
    out = np.zeros((len(codes), 3), np.int64)
    for k, code in enumerate(codes):
        code = int(code)
        if code in (0, 7):
            error = int(error or armed)                    # Invalid codes flag once armed.
        else:
            armed = True
            new = HALL_SECTORS[code]
            if new != sector:
                forward   = (new == (sector + 1) % 6) ^ bool(invert)
                direction = int(not forward)
                sector    = new
        out[k] = (sector, direction, error)
    return out[:, 0], out[:, 1], out[:, 2]

# Motor Control: Observers -------------------------------------------------------------------------

def angle_tracker_model(angles, kp_shift=4, ki_shift=10, angle_width=16, frac_bits=14,
    angle_offset=0):
    """Bit-exact reference for litedsp.motor.observer.LiteDSPAngleTracker.

    Per accepted sample: the output is the current estimate ``theta >> frac``; then the wrapped
    error ``e = angle - (theta >> frac)`` updates ``theta += integral + (e_frac >> kp)`` and
    ``integral += e_frac >> ki`` (``e_frac = e << frac``, all wrapping at the RTL widths).
    Returns ``(angles_out, speeds)``; shifts may be per-sample arrays.
    """
    n     = len(angles)
    W     = angle_width + frac_bits + 2
    wrap  = _wrapper(W)
    wa    = _wrapper(angle_width)
    mask  = (1 << (angle_width + frac_bits)) - 1
    kp, ki = _per_sample(kp_shift, n), _per_sample(ki_shift, n)
    theta = integral = 0
    out, speeds = np.zeros(n, np.int64), np.zeros(n, np.int64)
    for k, a in enumerate(np.asarray(angles, np.int64)):
        out[k]   = wa((theta >> frac_bits) + angle_offset)
        err      = wa(int(a) - (theta >> frac_bits))
        e_frac   = wrap(err << frac_bits)
        loop_out = wrap(integral + (e_frac >> int(kp[k])))
        theta    = (theta + loop_out) & mask
        integral = wrap(integral + (e_frac >> int(ki[k])))
        speeds[k] = integral
    return out, speeds

def smo_model(i_a, i_b, v_a, v_b, g_v, g_r, k_sm, lpf_shift=3, data_width=16, angle_width=16,
    gain_width=16, gain_frac=12, stages=None):
    """Bit-exact reference for litedsp.motor.observer.LiteDSPSMObserver: raw back-EMF angle
    per accepted (i, v) pair (the state advances per pair; the CORDIC sees the updated EMF)."""
    IW, EW = data_width + 2, data_width + 1
    ih, emf = [0, 0], [0, 0]
    out = np.zeros(len(i_a), np.int64)
    for k, (ia, ib, va, vb) in enumerate(zip(i_a, i_b, v_a, v_b)):
        emf_n, ih_n = [0, 0], [0, 0]
        for ax, (i, v) in enumerate(((int(ia), int(va)), (int(ib), int(vb)))):
            err    = ih[ax] - i
            z      = -int(k_sm) if err < 0 else int(k_sm)
            emf_n[ax] = emf[ax] + ((z - emf[ax]) >> lpf_shift)
            d      = v - emf[ax] - z
            upd    = d*int(g_v) - ih[ax]*int(g_r)
            ih_n[ax] = int(np_saturated(np.int64(ih[ax] + int(np_rounded(np.int64(upd), gain_frac))), IW))
        out[k] = cordic_vectoring_model(emf_n[1], -emf_n[0], EW, angle_width, stages)
        ih, emf = ih_n, emf_n
    return out

def pmsm_steady_state(omega_pu, iq_pu, r_pu=0.05, l_pu=0.3, psi_pu=0.6, n=2000, wb_ts=0.1,
    id_pu=0.0, data_width=16, theta0=0.0):
    """Float per-unit PMSM at constant speed (test stimulus): returns Q1.(N-1) integer arrays
    ``(i_alpha, i_beta, v_alpha, v_beta, theta)`` with ``theta`` the true electrical angle in
    angle units of a 16-bit turn. ``wb_ts = w_b*Ts`` sets the angle step per sample."""
    fs    = (1 << (data_width - 1)) - 1
    theta = theta0 + omega_pu*wb_ts*np.arange(n)
    v_d   = r_pu*id_pu - omega_pu*l_pu*iq_pu
    v_q   = r_pu*iq_pu + omega_pu*l_pu*id_pu + omega_pu*psi_pu
    i_ab  = (id_pu + 1j*iq_pu)*np.exp(1j*theta)
    v_ab  = (v_d + 1j*v_q)*np.exp(1j*theta)
    q     = lambda x: np.clip(np.round(x*fs), -fs, fs).astype(np.int64)
    return (q(i_ab.real), q(i_ab.imag), q(v_ab.real), q(v_ab.imag),
            np.round(theta/(2*np.pi)*(1 << 16)).astype(np.int64))

# Motor Control: Resolver ----------------------------------------------------------------------------

def resolver_model(sin_in, cos_in, decimation=32, phase_offset=0, data_width=16, angle_width=16,
    kp_shift=3, ki_shift=8, frac_bits=14, stages=None):
    """Bit-exact reference for litedsp.motor.resolver.LiteDSPResolverDigital.

    Returns ``(exc, raw_angles, angles)``: the excitation sample per accepted input, the
    demodulated angle per excitation period (CORDIC at the accumulator width) and the tracked
    angle stream (one per period).
    """
    D     = decimation
    scale = (1 << (data_width - 1)) - 1
    ref   = np.round(np.sin(2*np.pi*np.arange(D)/D)*scale).astype(np.int64)
    AW    = 2*data_width + int(math.ceil(math.log2(D)))
    if stages is None:
        stages = angle_width
    exc, raw = [], []
    acc_s = acc_c = 0
    for k, (s, c) in enumerate(zip(np.asarray(sin_in, np.int64), np.asarray(cos_in, np.int64))):
        phase = k % D
        exc.append(int(ref[phase]))
        dem   = int(ref[(phase + phase_offset) % D])
        acc_s += int(s)*dem
        acc_c += int(c)*dem
        if phase == D - 1:
            raw.append(cordic_vectoring_model(acc_c, acc_s, AW - 1, angle_width, stages))
            acc_s = acc_c = 0
    angles, _ = angle_tracker_model(raw, kp_shift, ki_shift, angle_width, frac_bits)
    return np.array(exc, np.int64), np.array(raw, np.int64), angles

def resolver_stimulus(theta, decimation=32, delay=0, amplitude=0.8, data_width=16):
    """Float resolver windings (test stimulus): ``sin(theta)*ref`` / ``cos(theta)*ref`` with the
    excitation carrier delayed by ``delay`` samples (analog loop delay); theta in radians per
    sample. Returns Q1.(N-1) integer (sin_in, cos_in)."""
    D     = decimation
    scale = (1 << (data_width - 1)) - 1
    k     = np.arange(len(theta))
    ref   = np.sin(2*np.pi*((k - delay) % D)/D)
    q     = lambda x: np.clip(np.round(x*scale), -scale, scale).astype(np.int64)
    return q(amplitude*np.sin(theta)*ref), q(amplitude*np.cos(theta)*ref)

# Motor Control: FOC -------------------------------------------------------------------------------

def foc_model(a, b, c, angle, setpoint_d, setpoint_q, kp_d, ki_d, kp_q, ki_q, limit=None,
    data_width=16, angle_width=16, lut_depth=1024, three_wire=False, gain_width=16,
    gain_frac=12, anti_windup="conditional", open_loop=0, voltage_d=0, voltage_q=0,
    decoupling=False, speed=0, l_pu=0, psi_pu=0):
    """Bit-exact reference for litedsp.motor.foc.LiteDSPFOC: the composed block models
    (Clarke -> Park -> d/q controller -> inverse Park -> SVPWM), sample-aligned. Returns the
    (a, b, c) duties."""
    alpha, beta = clarke_model(a, b, c, data_width, three_wire)
    cos, sin    = sincos_model(angle, data_width, angle_width, lut_depth)
    i_d, i_q    = mixer_model(alpha, beta, cos, sin, mode="down", data_width=data_width)
    v_d, v_q    = dq_controller_model(i_d, i_q, setpoint_d, setpoint_q, kp_d, ki_d, kp_q, ki_q,
        limit, data_width, gain_width, gain_frac, anti_windup, open_loop, voltage_d, voltage_q,
        decoupling, speed, l_pu, psi_pu)
    v_a, v_b    = mixer_model(v_d, v_q, cos, sin, mode="up", data_width=data_width)
    return svpwm_model(v_a, v_b, 1, data_width)

# Audio: Level -------------------------------------------------------------------------------------

def volume_model(x, channel, gains, mute=0, n_channels=2, ramp_shift=8, gain_frac=19,
    data_width=24, ramp_enable=1):
    """Bit-exact reference for litedsp.audio.level.LiteDSPVolume.

    ``x``/``channel`` are the accepted beats; ``gains`` is a list of ``n_channels`` targets
    (each a scalar or a per-beat array), ``mute`` a per-beat mask (or scalar). Per beat of
    channel c: ``delta = target - applied[c]``; ``step = delta >> ramp_shift`` (arithmetic),
    or +/-1 when that is zero but delta is not; ``applied[c] += step`` (or = target without
    ramping); ``y = round(x*applied)`` saturated. Returns the output samples.
    """
    x       = np.asarray(x, np.int64)
    n       = len(x)
    channel = _per_sample(channel, n)
    mute    = _per_sample(mute, n)
    ramp    = _per_sample(ramp_enable, n)
    gains   = [_per_sample(g, n) for g in gains]
    applied = [1 << gain_frac]*n_channels
    out     = np.zeros(n, np.int64)
    for k in range(n):
        c      = int(channel[k])
        target = 0 if (int(mute[k]) >> c) & 1 else int(gains[c][k])
        delta  = target - applied[c]
        step   = delta >> ramp_shift
        if step == 0 and delta != 0:
            step = 1 if delta > 0 else -1
        applied[c] = applied[c] + step if ramp[k] else target
        out[k] = np_scaled(np.int64(int(x[k])*applied[c]), gain_frac, data_width)
    return out

def stereo_matrix_model(l, r, a, b, c, d, coeff_frac=15, data_width=24):
    """Bit-exact reference for litedsp.audio.level.LiteDSPStereoMatrix: (L', R') per frame."""
    l, r = np.asarray(l, np.int64), np.asarray(r, np.int64)
    return (np_scaled(a*l + b*r, coeff_frac, data_width), np_scaled(c*l + d*r, coeff_frac, data_width))

# Audio: Dither ------------------------------------------------------------------------------------

def xorshift32(state):
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    state ^= (state << 5) & 0xFFFFFFFF
    return state & 0xFFFFFFFF

def dither_model(x, channel, out_width=16, n_channels=2, shaping="none", seed=0x2545F491,
    data_width=24, dither_enable=1, shaping_enable=None):
    """Bit-exact reference for litedsp.audio.dither.LiteDSPDither.

    Per accepted beat: ``u = x + feedback`` (``ef1``: e1, ``ef2``: 2e1 - e2 of the channel),
    TPDF dither from the low ``shift`` bits of two xorshift32 generators (advanced per beat),
    round-half-up to ``out_width``, saturate; the fed-back error ``u - q`` includes the dither
    so it is shaped too. Returns the MSB-aligned ``data_width`` output words; the enables may
    be per-beat arrays.
    """
    x       = np.asarray(x, np.int64)
    n       = len(x)
    shift   = data_width - out_width
    channel = _per_sample(channel, n)
    d_en    = _per_sample(dither_enable, n)
    s_en    = _per_sample(int(shaping != "none") if shaping_enable is None else shaping_enable, n)
    r0, r1  = seed & 0xFFFFFFFF, ((seed*0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF) or 1
    e1, e2  = [0]*n_channels, [0]*n_channels
    out     = np.zeros(n, np.int64)
    mask    = (1 << shift) - 1
    for k in range(n):
        c    = int(channel[k])
        tpdf = ((r0 & mask) + (r1 & mask) - (1 << shift)) if d_en[k] else 0
        fb   = 0
        if s_en[k] and shaping == "ef1":
            fb = e1[c]
        elif s_en[k] and shaping == "ef2":
            fb = 2*e1[c] - e2[c]
        u    = int(x[k]) + fb
        v    = u + tpdf
        q_r  = int(np_rounded(np.int64(v), shift))
        q    = int(np_saturated(np.int64(q_r), out_width))
        e2[c], e1[c] = e1[c], u - (q_r << shift)
        out[k] = q << shift
        r0, r1 = xorshift32(r0), xorshift32(r1)
    return out

# Audio: Equalizer ---------------------------------------------------------------------------------

def audio_eq_model(x, channel, sections, n_channels=2, data_width=24, frac_bits=28,
    error_feedback=1, band_enable=None):
    """Bit-exact reference for litedsp.audio.eq.LiteDSPAudioEQ.

    Per accepted beat of channel c, the ``sections`` (dicts ``b0, b1, b2, a1, a2`` in
    Q.frac_bits) run in cascade with per-(channel, band) DF1 state: ``acc = fb + b0*x + b1*x1
    + b2*x2 - a1*y1 - a2*y2`` (``fb`` = e1 or 2e1 - e2), ``y = sat(round(acc / 2**frac))``,
    ``e = acc - round(acc)*2**frac``; a disabled band passes its input through and refreshes
    its history with it. ``band_enable`` may be a per-beat array of masks. Returns the output.
    """
    x       = np.asarray(x, np.int64)
    n       = len(x)
    n_bands = len(sections)
    channel = _per_sample(channel, n)
    mask    = _per_sample((1 << n_bands) - 1 if band_enable is None else band_enable, n)
    st      = {(c, b): dict(x1=0, x2=0, y1=0, y2=0, e1=0, e2=0)
               for c in range(n_channels) for b in range(n_bands)}
    out     = np.zeros(n, np.int64)
    for k in range(n):
        c = int(channel[k])
        v = int(x[k])
        for b, s in enumerate(sections):
            q = st[(c, b)]
            if (int(mask[k]) >> b) & 1:
                fb  = q["e1"] if error_feedback == 1 else (2*q["e1"] - q["e2"] if error_feedback == 2 else 0)
                acc = fb + s["b0"]*v + s["b1"]*q["x1"] + s["b2"]*q["x2"] - s["a1"]*q["y1"] - s["a2"]*q["y2"]
                y_r = int(np_rounded(np.int64(acc), frac_bits))
                y   = int(np_saturated(np.int64(y_r), data_width))
                e   = acc - (y_r << frac_bits)
            else:
                y, e = v, 0
            st[(c, b)] = dict(x1=v, x2=q["x1"], y1=y, y2=q["y1"], e1=e, e2=q["e1"])
            v = y
        out[k] = v
    return out

# Audio: Dynamics ----------------------------------------------------------------------------------

def compressor_model(x, channel, threshold, slope_above, slope_below, attack, release, gr_max,
    makeup=0, detector=0, rms_shift=6, stereo_link=0, n_channels=2, data_width=24, lookahead=0):
    """Bit-exact reference for litedsp.audio.dynamics.LiteDSPCompressor.

    Per accepted beat (channel c): mean square ``sq[c] += (x*x - sq[c]) >> rms_shift``; level
    ``L`` (Q.8 log2 re FS) from the LUT log2 of ``|x| << DW`` (peak) or ``sq`` (rms, halved);
    stereo link uses the previous frame's maximum level and one smoother; ``gr = clamp(slope*
    |L - thr| >> 16, gr_max)`` on the matching side; ``gr_s += ((gr << 16) - gr_s)*alpha >>
    16`` (Q7.24, clamped); ``g = clip(makeup - (gr_s >> 16))`` -> exp2 -> Q5.19 gain; output
    ``sat(round(x_delayed*gain / 2**19))`` with ``x_delayed`` the same channel ``lookahead``
    frames earlier. Returns ``(y, gr)``.
    """
    DW = data_width
    x  = np.asarray(x, np.int64)
    n  = len(x)
    ch = _per_sample(channel, n)
    L_OFF_PK, L_OFF_RMS = (2*DW - 1)*256, (DW - 1)*256
    sq, gr_s = [0]*n_channels, [0]*n_channels
    L_max, L_link = -(1 << 15), -(1 << 15)
    out, grs = np.zeros(n, np.int64), np.zeros(n, np.int64)
    for k in range(n):
        c   = int(ch[k])
        xv  = int(x[k])
        xd  = int(x[k - lookahead*n_channels]) if k >= lookahead*n_channels else 0
        mag = abs(xv)
        sq[c] = max(0, sq[c] + ((xv*xv - sq[c]) >> rms_shift))
        lin = sq[c] if detector else (mag << DW)
        lg  = int(log2_model([lin], 2*DW, 8, lut=True)[0])
        L   = ((lg >> 1) - L_OFF_RMS) if detector else (lg - L_OFF_PK)
        L_use = L_link if stereo_link else L
        if L > L_max:
            L_max = L
        if c == n_channels - 1:
            L_link, L_max = max(L, L_max), -(1 << 15)
        over  = L_use - int(threshold)
        slope = int(slope_below) if over < 0 else int(slope_above)
        gr    = min((slope*abs(over)) >> 16, int(gr_max))
        s     = 0 if stereo_link else c
        tgt   = gr << 16
        alpha = int(attack) if tgt > gr_s[s] else int(release)
        gr_s[s] = max(0, min((1 << 31) - 1, gr_s[s] + (((tgt - gr_s[s])*alpha) >> 16)))
        g_log = int(makeup) - (gr_s[s] >> 16)
        g_log = max(-47*256, min(4*256, g_log))
        gain  = int(exp2_model([g_log], 16, 8, 19, 24)[0])
        out[k] = np_scaled(np.int64(xd*gain), 19, DW)
        grs[k] = gr
    return out, grs

# Audio: Effects -----------------------------------------------------------------------------------

def lfo_model(phase_inc, n, shape=0, amplitude=None, phase_bits=32, data_width=16, lut_depth=256):
    """Bit-exact reference for litedsp.audio.effects.LiteDSPLFO: n samples of the shape
    (0 sine, 1 triangle, 2 saw, 3 square) at the Q1.15 amplitude."""
    DW = data_width
    FS = (1 << (DW - 1)) - 1
    if amplitude is None:
        amplitude = FS
    addr_bits = int(round(np.log2(lut_depth)))
    _, sin_t  = nco_lut(lut_depth, DW)
    mask, wrap = (1 << phase_bits) - 1, _wrapper(DW)
    phase, out = 0, np.zeros(n, np.int64)
    for k in range(n):
        phase = (phase + phase_inc) & mask
        saw   = wrap(phase >> (phase_bits - DW))
        if shape == 0:
            v = int(sin_t[phase >> (phase_bits - addr_bits)])
        elif shape == 1:
            v = int(np_saturated(np.int64(2*abs(saw) - (1 << (DW - 1))), DW))
        elif shape == 2:
            v = saw
        else:
            v = -FS if saw < 0 else FS
        out[k] = np_scaled(np.int64(v*amplitude), DW - 1, DW)
    return out

def delay_line_model(x, channel, delay, feedback=0, damping=0, wet=1 << 14, dry=1 << 14,
    mod=None, mod_depth=0, n_channels=2, max_delay=64, coeff_frac=15, mod_frac=8,
    modulation=False, data_width=24):
    """Bit-exact reference for litedsp.audio.effects.LiteDSPDelayLine.

    ``mod`` is the per-frame modulation sample list (consumed at each channel-0 beat when
    ``modulation``). Per beat: integer/fractional delay (clamped to 1..max_delay-2 frames),
    reads d0/d1 one frame apart with linear interpolation, damping one-pole, feedback write
    ``sat(x + feedback*filt)``, mix ``round((dry*x + wet*d) / 2**coeff_frac)`` saturated.
    """
    DW, CF, MF = data_width, coeff_frac, mod_frac
    depth = 1
    while depth < max_delay:
        depth *= 2
    x  = np.asarray(x, np.int64)
    n  = len(x)
    ch = _per_sample(channel, n)
    dl = _per_sample(delay, n)
    buf  = [[0]*n_channels for _ in range(depth)]
    filt = [0]*n_channels
    ptr, mod_idx, mod_cur = 0, 0, 0
    out = np.zeros(n, np.int64)
    for k in range(n):
        c, xv = int(ch[k]), int(x[k])
        if modulation and c == 0:
            mod_cur, mod_idx = int(mod[mod_idx]), mod_idx + 1
        if modulation:
            d_full = (int(dl[k]) << MF) + ((int(mod_depth)*mod_cur) >> (15 - MF))
            d_full = max(1 << MF, min((max_delay - 2) << MF, d_full))
            d_int, frac = d_full >> MF, d_full & ((1 << MF) - 1)
        else:
            d_int, frac = max(1, min(max_delay - 2, int(dl[k]))), 0
        d0 = buf[(ptr - d_int) % depth][c]
        d1 = buf[(ptr - d_int - 1) % depth][c]
        d  = int(np_saturated(np.int64(d0 + (((d1 - d0)*frac) >> MF)), DW)) if modulation else d0
        filt_n  = int(np_saturated(np.int64(filt[c] + (((d - filt[c])*((1 << 15) - int(damping))) >> 15)), DW))
        filt[c] = filt_n
        buf[ptr][c] = int(np_saturated(np.int64(xv + ((filt_n*int(feedback)) >> CF)), DW))
        out[k] = np_scaled(np.int64(xv*int(dry) + d*int(wet)), CF, DW)
        if c == n_channels - 1:
            ptr = (ptr + 1) % depth
    return out

def wet_dry_mix_model(dry_x, wet_x, wet, dry, coeff_frac=15, data_width=24):
    """Bit-exact reference for litedsp.audio.effects.LiteDSPWetDryMix."""
    return np_scaled(np.asarray(dry_x, np.int64)*int(dry) + np.asarray(wet_x, np.int64)*int(wet),
        coeff_frac, data_width)

def reverb_model(x, channel, room_size, damping, allpass_gain, wet, dry, comb_delays,
    allpass_delays, stereo_spread=23, n_channels=2, coeff_frac=15, data_width=24):
    """Bit-exact reference for litedsp.audio.effects.LiteDSPReverb: parallel combs (delay
    lines with wet 1/n, feedback = room_size, damping) summed with saturation, series
    allpasses (feedback g, dry -g, wet 1), wet/dry mix with the input."""
    x  = np.asarray(x, np.int64)
    n  = len(x)
    ch = _per_sample(channel, n)
    spread = stereo_spread*(n_channels - 1)
    n_combs = len(comb_delays)
    acc = np.zeros(n, np.int64)
    for d in comb_delays:
        acc += delay_line_model(x, ch, d + ch*stereo_spread, feedback=room_size, damping=damping,
            wet=(1 << coeff_frac)//n_combs, dry=0, n_channels=n_channels, max_delay=d + spread + 2,
            coeff_frac=coeff_frac, data_width=data_width)
    r = np_saturated(acc, data_width)
    for d in allpass_delays:
        r = delay_line_model(r, ch, d + ch*stereo_spread, feedback=allpass_gain, damping=0,
            wet=(1 << coeff_frac) - 1, dry=-int(allpass_gain), n_channels=n_channels,
            max_delay=d + spread + 2, coeff_frac=coeff_frac, data_width=data_width)
    return wet_dry_mix_model(x, r, wet, dry, coeff_frac, data_width)

def peak_meter_model(x, channel, n_channels=2, decay_shift=12, clip_threshold=None, data_width=24):
    """Bit-exact reference for litedsp.audio.meter.LiteDSPPeakMeter: per accepted beat of
    channel c, ``peak = max(|x|, peak - max(peak >> decay_shift, 1))`` (floored at 0), ``hold =
    max(hold, |x|)``, ``|x| >= clip_threshold`` counts a clip (saturating 16-bit) and sets the
    sticky flag. Returns ``(peak_after_beat, hold_after_beat, clip_count, clip)`` with per-beat
    arrays for the beat's channel and final per-channel lists."""
    x   = np.asarray(x, np.int64)
    n   = len(x)
    ch  = _per_sample(channel, n)
    ds  = _per_sample(decay_shift, n)
    thr = (1 << (data_width - 1)) - 1 if clip_threshold is None else int(clip_threshold)
    peak, hold, count, clip = [0]*n_channels, [0]*n_channels, [0]*n_channels, [0]*n_channels
    out_p, out_h = np.zeros(n, np.int64), np.zeros(n, np.int64)
    for k in range(n):
        c, m = int(ch[k]), abs(int(x[k]))
        fall = max(peak[c] >> int(ds[k]), 1)
        dec  = peak[c] - fall if peak[c] > fall else 0
        peak[c] = max(m, dec)
        hold[c] = max(hold[c], m)
        if m >= thr:
            clip[c]  = 1
            count[c] = min(count[c] + 1, 0xffff)
        out_p[k], out_h[k] = peak[c], hold[c]
    return out_p, out_h, count, clip

def loudness_model(x, channel, sections, n_channels=2, hop_samples=64, channel_weights=None,
    data_width=24, frac_bits=28):
    """Bit-exact reference for litedsp.audio.meter.LiteDSPLoudness: K-weighting through
    ``audio_eq_model`` (error feedback 1), ``term = (y*y*w[c]) >> 14`` (weights Q2.14, default
    1.0), summed over ``hop_samples*n_channels`` beats. Returns the list of completed hop sums."""
    x  = np.asarray(x, np.int64)
    n  = len(x)
    ch = _per_sample(channel, n)
    w  = [1 << 14]*n_channels if channel_weights is None else [int(v) for v in channel_weights]
    y  = audio_eq_model(x, ch, sections, n_channels, data_width, frac_bits, error_feedback=1)
    hop_beats = hop_samples*n_channels
    hops, acc = [], 0
    for k in range(n):
        acc += (int(y[k])*int(y[k])*w[int(ch[k])]) >> 14
        if (k + 1) % hop_beats == 0:
            hops.append(acc)
            acc = 0
    return hops

def tdm_mux_model(channels):
    """Reference for litedsp.stream.route.LiteDSPTDMMux: strict round-robin interleave of the
    per-channel sample lists; returns ``(data, channel)`` beat arrays."""
    n_ch, n = len(channels), min(len(c) for c in channels)
    data = np.array([int(channels[k % n_ch][k//n_ch]) for k in range(n_ch*n)], np.int64)
    return data, np.array([k % n_ch for k in range(n_ch*n)], np.int64)

def sigma_delta_model(x, interpolation=64, order=2, data_width=24):
    """Bit-exact reference for litedsp.audio.pdm.LiteDSPSigmaDeltaModulator: zero-order hold of
    each sample for ``interpolation`` bits, error feedback ``u = x + e1`` (order 1) or ``x + 2 e1
    - e2`` (order 2), ``bit = u >= 0``, ``e = u -/+ 2**(data_width - 1)`` saturated to
    ``data_width + 2`` bits. Returns the bit array."""
    FS, EW = 1 << (data_width - 1), data_width + 2
    e1 = e2 = 0
    bits = []
    for v in np.asarray(x, np.int64):
        v = int(v)
        for _ in range(int(interpolation)):
            u = v + e1 if order == 1 else v + 2*e1 - e2
            b = 1 if u >= 0 else 0
            e = u - (FS if b else -FS)
            e2, e1 = e1, int(np_saturated(np.array([e]), EW)[0])
            bits.append(b)
    return np.array(bits, np.int64)

def pdm_receiver_model(bits, decimation=64, n_stages=4, data_width=24, with_dc_blocker=True,
    dc_pole_shift=10, comp_coefficients=None):
    """Bit-exact reference for litedsp.audio.pdm.LiteDSPPDMReceiver: per channel the bitstream
    decimator, the mono DC blocker (8 fractional bits) and the droop-compensation FIR, then the
    TDM interleave. ``bits`` is a list of per-channel bit arrays; returns ``(data, channel)``."""
    outs = []
    for b in bits:
        y = bitstream_decimator_model(np.asarray(b, np.int64), decimation, n_stages, 1, data_width)
        if with_dc_blocker:
            y = dc_blocker_model(y, pole_shift=dc_pole_shift, data_width=data_width, precision_bits=8)
        if comp_coefficients is not None:
            y = fir_model(y, comp_coefficients, data_width)
        outs.append(np.asarray(y, np.int64))
    return tdm_mux_model(outs)

def i2s_params(fmt, sample_width, slot_width):
    """``(msb_pos, polarity)`` of a serial audio format (see litedsp.audio.i2s)."""
    return {"i2s": (1, 0), "left_justified": (0, 1), "right_justified": (slot_width - sample_width, 1),
            "tdm": (1, None)}[fmt]

def i2s_frame_model(frames, fmt="i2s", sample_width=24, slot_width=32, n_channels=2):
    """Reference for litedsp.audio.i2s.LiteDSPI2STransmitter: ``frames`` is a list of
    ``n_channels``-word lists (signed ``sample_width``-bit integers); returns the ``(sdata,
    lrck)`` bit lists, one entry per BCLK period (the levels sampled on the rising edge)."""
    msb_pos, pol = i2s_params(fmt, sample_width, slot_width)
    words = [int(w) for frame in frames for w in frame]
    sdata, lrck = [], []
    prev = None
    for i, w in enumerate(words):
        slot = i % n_channels
        for pos in range(slot_width):
            k, k_prev = pos - msb_pos, pos + slot_width - msb_pos
            if 0 <= k < sample_width:
                b = (w >> (sample_width - 1 - k)) & 1
            elif k < 0 and prev is not None and k_prev < sample_width:
                b = (prev >> (sample_width - 1 - k_prev)) & 1
            else:
                b = 0
            sdata.append(b)
            lrck.append(int(pos == 0 and slot == 0) if pol is None else int((slot == 0) == bool(pol)))
        prev = w
    return sdata, lrck

def bit_reverse_model(cols, N):
    """Bit-exact reference for litedsp.analysis.reorder.LiteDSPBitReverse: every N-beat frame of
    each column is reordered from bit-reversed to natural order (``out[b] = in[bitrev(b)]``);
    beats of an incomplete trailing frame are not emitted."""
    bits = (N - 1).bit_length()
    rev  = [int("".join(reversed(f"{k:0{bits}b}")), 2) for k in range(N)]
    out  = []
    for c in cols:
        c = np.asarray(c, np.int64)
        n = (len(c)//N)*N
        out.append(np.concatenate([c[f:f + N][rev] for f in range(0, n, N)]) if n else np.zeros(0, np.int64))
    return out

def range_gate_model(i, q, pri, gate_start, gate_len, n_pulses, enable=1, single=0, trigger=0):
    """Bit-exact reference for litedsp.radar.timing.LiteDSPRangeGate: a sample-domain PRI
    counter; samples inside the gate pass framed (``first`` at the gate start, ``last`` at its
    end). ``enable``/``trigger`` may be per-sample arrays; a trigger seen with sample k arms a
    single CPI from sample k + 1. Returns ``(i, q, first, last)`` of the gated samples."""
    i, q = np.asarray(i, np.int64), np.asarray(q, np.int64)
    n = len(i)
    en, trig = _per_sample(enable, n), _per_sample(trigger, n)
    t = pulse = 0
    armed = 0
    oi, oq, of, ol = [], [], [], []
    for k in range(n):
        running = int(en[k]) | armed
        if running:
            if gate_start <= t < gate_start + gate_len:
                oi.append(int(i[k])); oq.append(int(q[k]))
                of.append(int(t == gate_start)); ol.append(int(t == gate_start + gate_len - 1))
            if t == pri - 1:
                t = 0
                if pulse == n_pulses - 1:
                    pulse = 0
                    if not (trig[k] and single):
                        armed = 0
                else:
                    pulse += 1
            else:
                t += 1
        else:
            t = pulse = 0
        if trig[k] and single:
            armed = 1
    return (np.array(oi, np.int64), np.array(oq, np.int64), np.array(of, np.int64), np.array(ol, np.int64))

def pulse_compressor_model(i, q, first, last, pulse_len=16, bandwidth=0.5, data_width=16, window="rect",
    shift=None, phase_bits=32, lut_depth=1024):
    """Bit-exact reference for litedsp.radar.compress.LiteDSPPulseCompressor: the two real-tap
    complex FIRs (Re h on I/Q, Im h on I/Q) recombined with saturation, the framing tags delayed
    by ``pulse_len - 1`` beats (zeros before). Returns ``(i, q, first, last)``."""
    from litedsp.radar.waveform import pulse_compressor_taps
    if shift is None:
        shift = (data_width - 1) + (pulse_len - 1).bit_length()
    re_t, im_t = pulse_compressor_taps(pulse_len, bandwidth, data_width, window, phase_bits, lut_depth)
    ri, rq = fir_complex_model(i, q, re_t, data_width, shift)
    mi, mq = fir_complex_model(i, q, im_t, data_width, shift)
    oi = np_saturated(np.asarray(ri, np.int64) - np.asarray(mq, np.int64), data_width)
    oq = np_saturated(np.asarray(rq, np.int64) + np.asarray(mi, np.int64), data_width)
    n  = len(oi)
    d  = pulse_len - 1
    of = np.concatenate([np.zeros(min(d, n), np.int64), np.asarray(first, np.int64)[:max(0, n - d)]])
    ol = np.concatenate([np.zeros(min(d, n), np.int64), np.asarray(last, np.int64)[:max(0, n - d)]])
    return oi, oq, of, ol

def mti_model(i, q, first, n_range_bins, mode=1, shift=None, data_width=16):
    """Bit-exact reference for litedsp.radar.mti.LiteDSPMTICanceller: per range bin (counter
    reset by ``first``) ``y = x - x1`` (mode 0, rescaled by 1/2) or ``x - 2 x1 + x2`` (mode 1,
    rescaled by 1/4) against the previous pulses' samples (zero history after reset). ``mode``
    may be a per-sample array. Returns ``(i, q)``."""
    i, q = np.asarray(i, np.int64), np.asarray(q, np.int64)
    n = len(i)
    md = _per_sample(mode, n)
    h1 = np.zeros((n_range_bins, 2), np.int64)
    h2 = np.zeros((n_range_bins, 2), np.int64)
    oi, oq = np.zeros(n, np.int64), np.zeros(n, np.int64)
    r = 0
    for k in range(n):
        if first[k]:
            r = 0
        x = np.array([i[k], q[k]])
        m = int(md[k])
        diff = x - 2*h1[r] + h2[r] if m else x - h1[r]
        sh = (m + 1) if shift is None else shift
        y = np_scaled(diff, sh, data_width)
        oi[k], oq[k] = y[0], y[1]
        h2[r] = h1[r]
        h1[r] = x
        r = 0 if r == n_range_bins - 1 else r + 1
    return oi, oq

def corner_turn_model(i, q, n_range_bins, n_pulses):
    """Bit-exact reference for litedsp.radar.corner_turn.LiteDSPCornerTurn: each complete CPI
    (``n_pulses`` pulses of ``n_range_bins`` samples, arrival order) is transposed into
    ``n_range_bins`` columns of ``n_pulses`` samples. Returns ``(i, q, first, last)``."""
    i, q = np.asarray(i, np.int64), np.asarray(q, np.int64)
    n_cpi = len(i)//(n_range_bins*n_pulses)
    oi, oq = [], []
    for c in range(n_cpi):
        blk_i = i[c*n_range_bins*n_pulses:(c + 1)*n_range_bins*n_pulses].reshape(n_pulses, n_range_bins)
        blk_q = q[c*n_range_bins*n_pulses:(c + 1)*n_range_bins*n_pulses].reshape(n_pulses, n_range_bins)
        oi.append(blk_i.T.reshape(-1)); oq.append(blk_q.T.reshape(-1))
    n_out = n_cpi*n_range_bins*n_pulses
    first = np.array([int(k % n_pulses == 0) for k in range(n_out)], np.int64)
    last  = np.array([int(k % n_pulses == n_pulses - 1) for k in range(n_out)], np.int64)
    if n_cpi == 0:
        return np.zeros(0, np.int64), np.zeros(0, np.int64), first, last
    return np.concatenate(oi), np.concatenate(oq), first, last

def doppler_model(i, q, n_pulses, window="hann", magnitude="approx", data_width=16, twiddle_width=16,
    beta_shift=2):
    """Bit-exact reference for litedsp.radar.doppler.LiteDSPDopplerProcessor: per column of
    ``n_pulses`` beats (counted from the start of the stream) the window (``rect`` = none), the
    scaled fixed-point FFT, the magnitude (alpha-max-beta-min) or power, in natural bin order.
    Returns ``(data, first, last)`` for the complete columns."""
    from litedsp.analysis.window import window_coefficients
    i, q = np.asarray(i, np.int64), np.asarray(q, np.int64)
    if window != "rect":
        i, q = window_model(i, q, window_coefficients(n_pulses, window, data_width), data_width)
    n_cols = len(i)//n_pulses
    out = []
    for c in range(n_cols):
        fi, fq = fft_fixed_model(i[c*n_pulses:(c + 1)*n_pulses], q[c*n_pulses:(c + 1)*n_pulses],
            data_width, twiddle_width)
        fi, fq = np.asarray(fi, np.int64), np.asarray(fq, np.int64)
        if magnitude == "approx":
            m = magnitude_model(fi, fq, beta_shift)
        else:
            m = fi*fi + fq*fq
        out.append(bit_reverse_model([np.asarray(m, np.int64)], n_pulses)[0])
    n_out = n_cols*n_pulses
    first = np.array([int(k % n_pulses == 0) for k in range(n_out)], np.int64)
    last  = np.array([int(k % n_pulses == n_pulses - 1) for k in range(n_out)], np.int64)
    data  = np.concatenate(out) if out else np.zeros(0, np.int64)
    return data, first, last

def cfar_threshold(stat, alpha, recip, data_width, threshold_frac, threshold_min=0):
    """Threshold pipeline shared by the CFAR models: ``sat(rounded(stat*alpha*recip, frac+16))``
    floored at ``threshold_min``."""
    p2  = int(stat)*int(alpha)*int(recip)
    thr = (p2 + (1 << (threshold_frac + 15))) >> (threshold_frac + 16)
    return max(min(thr, (1 << data_width) - 1), int(threshold_min))

def os_cfar_model(x, first, last, n_train=4, n_guard=2, rank=5, alpha=1024, data_width=17, threshold_frac=8,
    threshold_min=0):
    """Bit-exact reference for litedsp.radar.cfar.LiteDSPOSCFAR: the CA-CFAR window with the
    statistic = ``rank``-th smallest (0-based) of the 2T training cells and
    ``threshold = rounded(stat * alpha, frac)``."""
    return _cfar_1d_model(x, first, last, n_train, n_guard, data_width, threshold_frac, threshold_min,
        lambda lead, lag: sorted(lead + lag)[rank], alpha, 1 << 16)

def ca_cfar_model(x, first, last, n_train=8, n_guard=2, alpha=512, mode=0, data_width=17, threshold_frac=8,
    threshold_min=0):
    """Bit-exact reference for litedsp.radar.cfar.LiteDSPCACFAR: the sliding window with the
    cell under test in the centre, zero padded at frame edges (``first`` clears the window, the
    trailing cells are flushed after ``last``), CA / GO / SO statistic, threshold and decision.
    Returns ``(data, threshold, detect, first, last)``, one beat per input cell."""
    def stat(lead, lag):
        a, b = sum(lead), sum(lag)
        return {0: a + b, 1: 2*max(a, b), 2: 2*min(a, b)}[int(mode)]
    return _cfar_1d_model(x, first, last, n_train, n_guard, data_width, threshold_frac, threshold_min,
        stat, alpha, int(round((1 << 16)/(2*n_train))))

def _cfar_1d_model(x, first, last, n_train, n_guard, data_width, threshold_frac, threshold_min, statistic,
    alpha, recip):
    """Software mirror of the 1-D CFAR window engine (``_cfar_window`` / ``_cfar_output``)."""
    T, G  = n_train, n_guard
    H, L  = T + G, 2*(T + G) + 1
    cells, real, firsts, lasts = [0]*L, [0]*L, [0]*L, [0]*L
    out = [[] for _ in range(5)]
    def evaluate():
        if real[H]:
            stat = statistic(cells[0:T], cells[H + G + 1:H + G + 1 + T])
            thr  = cfar_threshold(stat, alpha, recip, data_width, threshold_frac, threshold_min)
            for col, v in zip(out, (cells[H], thr, int(cells[H] > thr), firsts[H], lasts[H])):
                col.append(v)
    def push(cell, is_real, f, l):
        nonlocal cells, real, firsts, lasts
        evaluate()
        if is_real and f:
            cells, real, firsts, lasts = [int(cell)] + [0]*(L - 1), [1] + [0]*(L - 1), [1] + [0]*(L - 1), [int(l)] + [0]*(L - 1)
        else:
            cells  = [int(cell) if is_real else 0] + cells[:-1]
            real   = [int(is_real)] + real[:-1]
            firsts = [int(is_real and f)] + firsts[:-1]
            lasts  = [int(is_real and l)] + lasts[:-1]
    for k in range(len(x)):
        push(x[k], 1, first[k], last[k])
        if last[k]:
            for _ in range(H + 1):
                push(0, 0, 0, 0)
    return tuple(np.array(c, np.int64) for c in out)

def cfar_2d_model(x, n_range_bins=64, n_doppler_bins=16, n_train=(4, 2), n_guard=(1, 1), alpha=512,
    data_width=17, threshold_frac=8, threshold_min=0):
    """Bit-exact reference for litedsp.radar.cfar_2d.LiteDSPCFAR2D on whole CPIs of
    ``n_range_bins`` rows x ``n_doppler_bins`` cells (raster order, zero padded): box sum minus
    guard-box sum, threshold and decision. Returns ``(data, threshold, detect, first, last)``."""
    N, M   = n_range_bins, n_doppler_bins
    R, C   = n_train[0] + n_guard[0], n_train[1] + n_guard[1]
    gr, gd = n_guard
    n_tr   = (2*R + 1)*(2*C + 1) - (2*gr + 1)*(2*gd + 1)
    recip  = int(round((1 << 16)/n_tr))
    x      = np.asarray(x, np.int64)
    n_cpi  = len(x)//(N*M)
    out    = [[] for _ in range(5)]
    for k in range(n_cpi):
        m   = x[k*N*M:(k + 1)*N*M].reshape(N, M)
        pad = np.pad(m, ((R, R), (C, C)))
        for r in range(N):
            for c in range(M):
                big   = int(pad[r:r + 2*R + 1, c:c + 2*C + 1].sum())
                guard = int(pad[r + R - gr:r + R + gr + 1, c + C - gd:c + C + gd + 1].sum())
                thr   = cfar_threshold(big - guard, alpha, recip, data_width, threshold_frac, threshold_min)
                v     = int(m[r, c])
                for col, val in zip(out, (v, thr, int(v > thr), int(c == 0), int(c == M - 1))):
                    col.append(val)
    return tuple(np.array(c, np.int64) for c in out)

def parabolic_offset(y_prev, y0, y_next, frac_bits):
    """Integer parabolic sub-bin offset used by the peak extractor (Q.frac_bits): the bit-serial
    quotient of |y_next - y_prev| * 2^frac by 2 * (2 y0 - y_prev - y_next), clamped to +/-0.5 bin,
    0 when the curvature is not negative."""
    num = int(y_next) - int(y_prev)
    den = 2*(2*int(y0) - int(y_prev) - int(y_next))
    if den <= 0:
        return 0
    a = abs(num)
    if 2*a >= den:
        q = 1 << (frac_bits - 1)
    else:
        q = (a << frac_bits)//den
    return -q if num < 0 else q

def peak_extractor_model(data, detect, n_range_bins=64, n_doppler_bins=16, local_max=1, interpolate=1,
    frac_bits=4, index_width=12):
    """Bit-exact reference for litedsp.radar.detect.LiteDSPPeakExtractor on whole CPIs (raster
    order): records for detected cells that are strict maxima over their raster-earlier 3x3
    neighbours and no smaller than the later ones (all detected cells when ``local_max`` is 0),
    with parabolic sub-bin offsets, then the terminator beat. Returns ``(range, doppler, data,
    hit, first, last)``."""
    N, M, F = n_range_bins, n_doppler_bins, frac_bits
    data, detect = np.asarray(data, np.int64), np.asarray(detect, np.int64)
    out = [[] for _ in range(6)]
    for k in range(len(data)//(N*M)):
        m = np.pad(data[k*N*M:(k + 1)*N*M].reshape(N, M), 1)
        d = detect[k*N*M:(k + 1)*N*M].reshape(N, M)
        count = 0
        for r in range(N):
            for c in range(M):
                if not d[r, c]:
                    continue
                w  = m[r:r + 3, c:c + 3]
                y0 = int(w[1, 1])
                if local_max:
                    earlier = [w[0, 0], w[0, 1], w[0, 2], w[1, 0]]
                    later   = [w[1, 2], w[2, 0], w[2, 1], w[2, 2]]
                    if not (all(y0 > int(v) for v in earlier) and all(y0 >= int(v) for v in later)):
                        continue
                dr = parabolic_offset(w[0, 1], y0, w[2, 1], F) if interpolate else 0
                dc = parabolic_offset(w[1, 0], y0, w[1, 2], F) if interpolate else 0
                rec = (max(0, (r << F) + dr), max(0, (c << F) + dc), y0, 1, int(count == 0), 0)
                for col, v in zip(out, rec):
                    col.append(int(v))
                count += 1
        for col, v in zip(out, (0, 0, count, 0, int(count == 0), 1)):
            col.append(int(v))
    return tuple(np.array(c, np.int64) for c in out)

def target_list_model(rng, dop, data, hit, max_targets=16):
    """Bit-exact reference for litedsp.radar.detect.LiteDSPTargetList: per burst (records closed
    by a terminator with ``hit = 0``) the first ``max_targets`` records re-emitted framed, then
    the terminator with the kept count. Returns ``(range, doppler, data, hit, first, last)`` and
    the number of dropped records."""
    out, dropped, burst = [[] for _ in range(6)], 0, []
    for r, d, v, h in zip(rng, dop, data, hit):
        if h:
            burst.append((int(r), int(d), int(v)))
            continue
        kept = burst[:max_targets]
        dropped += len(burst) - len(kept)
        for i, (r_, d_, v_) in enumerate(kept):
            for col, val in zip(out, (r_, d_, v_, 1, int(i == 0), 0)):
                col.append(val)
        for col, val in zip(out, (0, 0, len(kept), 0, int(not kept), 1)):
            col.append(val)
        burst = []
    return tuple(np.array(c, np.int64) for c in out), dropped

def _sat(x, width):
    hi, lo = (1 << (width - 1)) - 1, -(1 << (width - 1))
    return max(lo, min(hi, int(x)))

def _rnd(x, shift):
    return int(x) if shift == 0 else (int(x) + (1 << (shift - 1))) >> shift

def alpha_beta_tracker_model(rng, dop, hit, n_tracks=4, alpha=128, beta=38, gate_r=32, gate_d=32,
    confirm_hits=3, max_misses=2, emit_tentative=0, index_width=12, frac_bits=4, velocity_frac=8,
    gain_frac=8):
    """Bit-exact reference for litedsp.radar.track.LiteDSPAlphaBetaTracker: serial gated
    nearest-neighbour association (lowest ``|dr| + |dd|``, lowest index on ties, lowest free
    slot for new tracks), alpha-beta update / coasting / confirmation / deletion on the
    terminator, then the framed track burst. Returns ``(range, doppler, velocity, id, hits, hit,
    first, last)`` and a dict of counters."""
    F, VF, GF, T = frac_bits, velocity_frac, gain_frac, n_tracks
    PW, PV, VW   = index_width + F, index_width + VF + 2, index_width + VF
    gr, gd = int(gate_r) << (VF - F), int(gate_d) << (VF - F)
    trk = [dict(state=0, P=[0, 0], pred=[0, 0], V=[0, 0], meas=[0, 0], assigned=0, hits=0, misses=0) for _ in range(T)]
    out = [[] for _ in range(8)]
    stats = dict(dropped=0, cpi_count=0)
    for r, d, h in zip(rng, dop, hit):
        if h:
            m = [int(r) << (VF - F), int(d) << (VF - F)]
            best, best_s = None, None
            for k, t in enumerate(trk):
                if t["state"] == 0 or t["assigned"]:
                    continue
                adr, add = abs(m[0] - t["pred"][0]), abs(m[1] - t["pred"][1])
                if adr <= gr and add <= gd and (best is None or adr + add < best_s):
                    best, best_s = k, adr + add
            if best is not None:
                trk[best]["meas"], trk[best]["assigned"] = list(m), 1
            else:
                free = [k for k, t in enumerate(trk) if t["state"] == 0]
                if free:
                    trk[free[0]] = dict(state=1, P=list(m), pred=list(m), V=[0, 0], meas=list(m), assigned=1, hits=0, misses=0)
                else:
                    stats["dropped"] += 1
            continue
        for t in trk:                                                   # Terminator: update.
            if t["state"] != 0:
                if t["assigned"]:
                    for a in range(2):
                        e = t["meas"][a] - t["pred"][a]
                        t["P"][a] = _sat(t["pred"][a] + _rnd(e*int(alpha), GF), PV)
                        t["V"][a] = _sat(t["V"][a] + _rnd(e*int(beta), GF), VW)
                    t["hits"], t["misses"] = min(15, t["hits"] + 1), 0
                    if t["state"] == 1 and t["hits"] >= confirm_hits:
                        t["state"] = 2
                else:
                    t["P"] = list(t["pred"])
                    t["misses"] += 1
                    if t["misses"] > max_misses:
                        t["state"] = 0
            t["assigned"] = 0
            t["pred"] = [_sat(t["P"][a] + t["V"][a], PV) for a in range(2)]
        active = sum(t["state"] != 0 for t in trk)
        n = 0
        for k, t in enumerate(trk):
            if t["state"] == 2 or (emit_tentative and t["state"] == 1):
                pos = [max(0, min((1 << PW) - 1, _rnd(t["P"][a], VF - F))) for a in range(2)]
                for col, v in zip(out, (pos[0], pos[1], t["V"][0], k, t["hits"], 1, int(n == 0), 0)):
                    col.append(v)
                n += 1
        for col, v in zip(out, (0, 0, 0, 0, active, 0, int(n == 0), 1)):
            col.append(v)
        stats["cpi_count"] += 1
    return tuple(np.array(c, np.int64) for c in out), stats

def tracker_scenario(n_cpi=12, seed=0, frac_bits=4, drop=((5, 0), (8, 1)), false_alarms=True):
    """Synthetic target bursts for the tracker tests: two crossing targets (range/Doppler in
    bins, constant velocity, +/-0.1 bin measurement noise), one random false alarm per CPI and
    dropped detections at ``drop`` = ((cpi, target), ...). Returns the beat dicts and the truth
    ``[(cpi, target, range, doppler)]``."""
    prng  = random.Random(seed)
    F     = frac_bits
    truth, beats = [], []
    targets = [((10.0, 3.0), (0.5, -0.25)), ((20.0, 2.0), (-0.5, 0.1))]
    for c in range(n_cpi):
        n = 0
        recs = []
        for k, ((r0, d0), (vr, vd)) in enumerate(targets):
            r, d = r0 + vr*c, d0 + vd*c
            truth.append((c, k, r, d))
            if (c, k) in drop:
                continue
            recs.append((int(round((r + prng.uniform(-0.1, 0.1))*(1 << F))), int(round((d + prng.uniform(-0.1, 0.1))*(1 << F))), 20000 - 1000*k))
        if false_alarms:                                                # Last in record order so
            recs.append((prng.randint(30 << F, 60 << F), prng.randint(0, 15 << F), 5000))   # the targets
        for r, d, v in recs:
            beats.append({"range": r, "doppler": d, "data": v, "hit": 1, "first": int(n == 0), "last": 0})
            n += 1
        beats.append({"range": 0, "doppler": 0, "data": n, "hit": 0, "first": int(n == 0), "last": 1})
    return beats, truth

def clutter_map_model(x, first, last, n_cells=64, alpha=1024, avg_shift=3, learn_all=0, freeze=0, data_width=17,
    threshold_frac=8, threshold_min=0):
    """Bit-exact reference for litedsp.radar.clutter.LiteDSPClutterMap: per-cell leaky sums
    (``sum += x - (sum >> avg_shift)``, censored unless ``learn_all``, frozen with ``freeze``),
    initialisation scan (full-scale threshold, no detection, until its ``last``), ``threshold =
    rounded(sum * alpha, frac + avg_shift)`` saturated and floored. ``first`` restarts the cell
    address. Returns ``(data, threshold, detect, first, last)``."""
    recip = 1 << (16 - avg_shift)
    sums  = [0]*n_cells
    out   = [[] for _ in range(5)]
    addr, init = 0, True
    for k in range(len(x)):
        if first[k]:
            addr = 0
        v = int(x[k])
        s = sums[addr]
        if init:
            thr, det = (1 << data_width) - 1, 0
            if not freeze:
                sums[addr] = v << avg_shift
        else:
            thr = cfar_threshold(s, alpha, recip, data_width, threshold_frac, threshold_min)
            det = int(v > thr)
            if not freeze and (learn_all or not det):
                sums[addr] = s + v - (s >> avg_shift)
        for col, val in zip(out, (v, thr, det, int(first[k]), int(last[k]))):
            col.append(val)
        if last[k]:
            init = False
        addr = (addr + 1) % n_cells
    return tuple(np.array(c, np.int64) for c in out)

def _clampc(x, width):
    return max(0, min((1 << width) - 1, int(x)))

def kalman_tracker_model(rng, dop, hit, n_tracks=4, q=13, r=128, p_vel0=1024, gate_r=32, gate_d=32,
    confirm_hits=3, max_misses=2, emit_tentative=0, index_width=12, frac_bits=4, velocity_frac=8,
    cov_frac=8, cov_width=24):
    """Bit-exact reference for litedsp.radar.kalman.LiteDSPKalmanTracker: the tracker engine of
    :func:`alpha_beta_tracker_model` with a constant-velocity Kalman update per axis (predicted
    covariance with process noise q, restoring-division gains, clamped covariance). Returns the
    track burst columns and a dict with the counters, the sticky ``cov_sat`` and the last gains
    per track."""
    F, VF, CF, CW, T = frac_bits, velocity_frac, cov_frac, cov_width, n_tracks
    PW, PV, VW   = index_width + F, index_width + VF + 2, index_width + VF
    NB, KW = CW + CF, CF + 4
    gr, gd = int(gate_r) << (VF - F), int(gate_d) << (VF - F)
    def new(m):
        return dict(state=1, P=list(m), pred=list(m), V=[0, 0], meas=list(m), assigned=1, hits=0, misses=0,
                    cov=[[int(r), 0, int(p_vel0)], [int(r), 0, int(p_vel0)]], gains=[[0, 0], [0, 0]])
    trk = [dict(state=0, P=[0, 0], pred=[0, 0], V=[0, 0], meas=[0, 0], assigned=0, hits=0, misses=0,
                cov=[[0, 0, 0], [0, 0, 0]], gains=[[0, 0], [0, 0]]) for _ in range(T)]
    out = [[] for _ in range(8)]
    stats = dict(dropped=0, cpi_count=0, cov_sat=0)
    for rr, dd, h in zip(rng, dop, hit):
        if h:
            m = [int(rr) << (VF - F), int(dd) << (VF - F)]
            best, best_s = None, None
            for k, t in enumerate(trk):
                if t["state"] == 0 or t["assigned"]:
                    continue
                adr, add = abs(m[0] - t["pred"][0]), abs(m[1] - t["pred"][1])
                if adr <= gr and add <= gd and (best is None or adr + add < best_s):
                    best, best_s = k, adr + add
            if best is not None:
                trk[best]["meas"], trk[best]["assigned"] = list(m), 1
            else:
                free = [k for k, t in enumerate(trk) if t["state"] == 0]
                if free:
                    trk[free[0]] = new(m)
                else:
                    stats["dropped"] += 1
            continue
        for t in trk:
            if t["state"] != 0:
                for a in range(2):
                    P11, P12, P22 = t["cov"][a]
                    s11, s12, s22 = P11 + 2*P12 + P22 + (int(q) >> 2), P12 + P22 + (int(q) >> 1), P22 + int(q)
                    if max(s11, s12, s22) > (1 << CW) - 1:
                        stats["cov_sat"] = 1
                    p11p, p12p, p22p = _clampc(s11, CW), _clampc(s12, CW), _clampc(s22, CW)
                    if t["assigned"]:
                        S  = p11p + int(r)
                        k1 = min((p11p << CF)//S, (1 << KW) - 1)
                        k2 = min((p12p << CF)//S, (1 << KW) - 1)
                        e  = t["meas"][a] - t["pred"][a]
                        t["P"][a] = _sat(t["pred"][a] + _rnd(e*k1, CF), PV)
                        t["V"][a] = _sat(t["V"][a] + _rnd(e*k2, CF), VW)
                        one = (1 << CF) - k1
                        t["cov"][a] = [_clampc(_rnd(p11p*one, CF), CW), _clampc(_rnd(p12p*one, CF), CW),
                                       _clampc(p22p - _rnd(p12p*k2, CF), CW)]
                        t["gains"][a] = [k1, k2]
                    else:
                        t["P"][a] = t["pred"][a]
                        t["cov"][a] = [p11p, p12p, p22p]
                if t["assigned"]:
                    t["hits"], t["misses"] = min(15, t["hits"] + 1), 0
                    if t["state"] == 1 and t["hits"] >= confirm_hits:
                        t["state"] = 2
                else:
                    t["misses"] += 1
                    if t["misses"] > max_misses:
                        t["state"] = 0
            t["assigned"] = 0
            t["pred"] = [_sat(t["P"][a] + t["V"][a], PV) for a in range(2)]
        active = sum(t["state"] != 0 for t in trk)
        n = 0
        for k, t in enumerate(trk):
            if t["state"] == 2 or (emit_tentative and t["state"] == 1):
                pos = [max(0, min((1 << PW) - 1, _rnd(t["P"][a], VF - F))) for a in range(2)]
                for col, v in zip(out, (pos[0], pos[1], t["V"][0], k, t["hits"], 1, int(n == 0), 0)):
                    col.append(v)
                n += 1
        for col, v in zip(out, (0, 0, 0, 0, active, 0, int(n == 0), 1)):
            col.append(v)
        stats["cpi_count"] += 1
    stats["gains"] = [t["gains"] for t in trk]
    return tuple(np.array(c, np.int64) for c in out), stats

def beamformer_model(xs, weights, shift=14, data_width=16):
    """Bit-exact reference for litedsp.radar.beamform.LiteDSPBeamformer: ``xs`` is a list of
    ``(i, q)`` arrays per element, ``weights`` a list per beam of ``(re, im)`` integer lists per
    element (signed Q(2).weight_frac); each sample yields the beams in order, ``y = scaled(sum_e
    w * x, shift)``. Returns ``(i, q, channel)`` and the saturation flag."""
    n = len(xs[0][0])
    oi, oq, ch = [], [], []
    sat = 0
    for k in range(n):
        for b, (wr, wi) in enumerate(weights):
            si = sum(int(wr[e])*int(xs[e][0][k]) - int(wi[e])*int(xs[e][1][k]) for e in range(len(xs)))
            sq = sum(int(wr[e])*int(xs[e][1][k]) + int(wi[e])*int(xs[e][0][k]) for e in range(len(xs)))
            ri, rq = _rnd(si, shift), _rnd(sq, shift)
            hi, lo = (1 << (data_width - 1)) - 1, -(1 << (data_width - 1))
            sat |= int(ri > hi or ri < lo or rq > hi or rq < lo)
            oi.append(max(lo, min(hi, ri))); oq.append(max(lo, min(hi, rq))); ch.append(b)
    return (np.array(oi, np.int64), np.array(oq, np.int64), np.array(ch, np.int64)), sat

def monopulse_model(a_i, a_q, b_i, b_q, data_width=16, angle_width=16, stages=None):
    """Bit-exact reference for litedsp.radar.beamform.LiteDSPMonopulse: the down-conversion mixer
    (``a * conj(b)``) followed by the vectoring CORDIC angle, per sample."""
    mi, mq = mixer_model(a_i, a_q, b_i, b_q, "down", data_width)[:2]
    return np.array([cordic_vectoring_model(int(x), int(y), data_width, angle_width, stages)
                     for x, y in zip(mi, mq)], np.int64)

def tvg_model(i, q, first, n_range_bins=1024, g0=0, k_log=0, k_lin=0, gain_frac=8, max_gain_log2=8, data_width=16,
    bypass=0):
    """Bit-exact reference for litedsp.radar.sonar.LiteDSPTVG: range counter (restarted by
    ``first``, held at the last bin), log2 ROM, clamped log-domain ramp, Exp2 (Q.14 gain) and
    the scaled product (or the plain sample with ``bypass``). Returns ``(i, q)``."""
    import math
    N, GF = n_range_bins, gain_frac
    GW = GF + max_gain_log2 + 1
    OF = 14
    rom = [0] + [int(round(math.log2(r)*(1 << GF))) for r in range(1, N)]
    hi, lo = (1 << (GW - 1)) - 1, -(1 << (GW - 1))
    r = 0
    oi, oq = [], []
    for k in range(len(i)):
        if first[k]:
            r = 0
        g  = int(g0) + _rnd(rom[r]*int(k_log), GF) + r*int(k_lin)
        g  = max(lo, min(hi, g))
        gain = int(exp2_model(np.array([g]), GW, GF, OF, OF + max_gain_log2 + 1)[0])
        if bypass:
            oi.append(int(i[k])); oq.append(int(q[k]))
        else:
            oi.append(_sat(_rnd(int(i[k])*gain, OF), data_width)); oq.append(_sat(_rnd(int(q[k])*gain, OF), data_width))
        r = 1 if first[k] else min(N - 1, r + 1)
    return np.array(oi, np.int64), np.array(oq, np.int64)

def pulse_generator_model(n_pulses=2, pulse_len=32, pri=128, bandwidth=0.5, data_width=16, phase_bits=32,
    lut_depth=1024):
    """Bit-exact reference for litedsp.radar.timing.LiteDSPPulseGenerator: ``n_pulses`` framed
    chirps (``chirp_reference``) each followed by zeros up to the PRI. Returns ``(i, q, first,
    last)``."""
    from litedsp.radar.waveform import chirp_reference
    pulse = chirp_reference(pulse_len, bandwidth, data_width, phase_bits, lut_depth)
    i, q, first, last = [], [], [], []
    for _ in range(n_pulses):
        for k in range(pri):
            v = pulse[k] if k < pulse_len else 0
            i.append(int(round(v.real))); q.append(int(round(v.imag)))
            first.append(int(k == 0)); last.append(int(k == pulse_len - 1))
    return tuple(np.array(c, np.int64) for c in (i, q, first, last))

# Image models -------------------------------------------------------------------------------------

PIXEL_BARS = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0), (1, 0, 1), (1, 0, 0), (0, 0, 1), (0, 0, 0)]

def pixel_pattern_model(mode="bars", width=16, height=12, data_width=8, n_channels=3, const=None):
    """Bit-exact reference for litedsp.image.pattern.LiteDSPPixelPattern: one frame as an
    (H, W) or (H, W, 3) array."""
    full  = (1 << data_width) - 1
    const = const or (full, full, full)
    bar_w = width >> 3
    img   = np.zeros((height, width, 3), np.int64)
    count = 0
    for y in range(height):
        bar = px = 0
        for x in range(width):
            bars = tuple(full if on else 0 for on in PIXEL_BARS[bar])
            if mode == "const":
                v = const
            elif mode == "ramp":
                v = (x & full, y & full, (x + y) & full)
            elif mode == "bars":
                v = bars
            elif mode == "checker":
                c = full if ((x >> 3) & 1) ^ ((y >> 3) & 1) else 0
                v = (c, c, c)
            elif mode == "counter":
                v = (count & full,)*3
            else:
                b = bars[2] if (y & 1 and x & 1) else bars[1] if (y & 1) ^ (x & 1) else bars[0]
                v = (b, b, b)
            img[y, x] = v
            count += 1
            if px == bar_w - 1 and bar != 7:
                px, bar = 0, bar + 1
            else:
                px += 1
    return img if n_channels == 3 else img[:, :, 0]

def video_frames(imgs, h_blank=6, v_blank=3, h_sync=2, v_sync=1):
    """LiteX-style timed video beats (``video_layout`` / ``video_timing_layout`` fields) for the
    (H, W, 3) frames ``imgs`` with horizontal / vertical blanking: ``de`` over the active area,
    ``hsync`` / ``vsync`` pulses at the start of the blanking intervals. Returns the beat dicts
    (with ``hcount`` / ``vcount`` / ``hres`` / ``vres`` for the timing generator)."""
    beats = []
    h, w = imgs[0].shape[:2]
    for y in range(v_blank):                                            # Leading vertical blanking:
        for x in range(w + h_blank):                                    # the adapter arms on vsync.
            beats.append({"hsync": int(w <= x < w + h_sync), "vsync": int(y < v_sync), "de": 0, "r": 0, "g": 0, "b": 0,
                          "hcount": x, "vcount": h + y, "hres": w, "vres": h})
    for img in imgs:
        h, w = img.shape[:2]
        for y in range(h + v_blank):
            for x in range(w + h_blank):
                de = int(x < w and y < h)
                beats.append({"hsync": int(w <= x < w + h_sync), "vsync": int(h <= y < h + v_sync), "de": de,
                              "r": int(img[y, x, 0]) if de else 0, "g": int(img[y, x, 1]) if de else 0,
                              "b": int(img[y, x, 2]) if de else 0,
                              "hcount": x, "vcount": y, "hres": w, "vres": h})
    return beats

def pixel_from_video_model(beats, width, height):
    """Bit-exact reference for litedsp.image.video.LiteDSPPixelFromVideo: the active pixels of
    ``beats`` (after the first vsync) as framed raster columns ``(r, g, b, eol, first, last)``."""
    r, g, b, eol, first, last = [], [], [], [], [], []
    armed, vs_d, de_d = False, 0, 0
    col = row = 0
    pending = False
    for bt in beats:
        if bt["vsync"] and not vs_d:
            armed, row, pending = True, 0, True
        if bt["de"]:
            c = 0 if not de_d else col
            if armed:
                r.append(bt["r"]); g.append(bt["g"]); b.append(bt["b"])
                eol.append(int(c == width - 1)); first.append(int(pending)); last.append(int(c == width - 1 and row == height - 1))
            pending = False
            col = c + 1
        elif de_d:
            col = 0
            if row != height - 1:
                row += 1
        vs_d, de_d = bt["vsync"], bt["de"]
    return tuple(np.array(v, np.int64) for v in (r, g, b, eol, first, last))

def pack_channels(img, data_width=8):
    """(H, W) or (H, W, 3) codes -> (H, W) packed words (channels LSB-first)."""
    img = np.asarray(img, np.int64)
    if img.ndim == 2:
        return img
    return sum(img[:, :, c] << (c*data_width) for c in range(img.shape[2]))

def np_pad_border(img, p, border="replicate"):
    """Pad a (H, W[, C]) image by ``p`` pixels: edge replication, mirror (``p[-1] = p[1]``) or zeros."""
    pad = [(p, p), (p, p)] + ([(0, 0)] if np.ndim(img) == 3 else [])
    return np.pad(img, pad, mode={"replicate": "edge", "mirror": "reflect", "zero": "constant"}[border])

def line_buffer_model(img, kernel_size=3, border="replicate", data_width=8):
    """Bit-exact reference for litedsp.image.linebuffer.LiteDSPLineBuffer on one frame: a dict of
    ``w{i}{j}`` raster columns (packed channels) plus ``eol``, ``first``, ``last``."""
    K, P = kernel_size, kernel_size//2
    packed = pack_channels(img, data_width)
    h, w   = packed.shape
    padded = np_pad_border(packed, P, border)
    out = {}
    for i in range(K):
        for j in range(K):
            out[f"w{i}{j}"] = padded[i:i + h, j:j + w].reshape(-1)
    out["eol"]   = np.array([int(k % w == w - 1) for k in range(w*h)], np.int64)
    out["first"] = np.array([int(k == 0) for k in range(w*h)], np.int64)
    out["last"]  = np.array([int(k == w*h - 1) for k in range(w*h)], np.int64)
    return out

def kernel2d_model(img, coefficients, shift=0, offset=0, kernel_size=3, border="replicate", data_width=8, bypass=0):
    """Bit-exact reference for litedsp.image.kernel.LiteDSPKernel2D on one frame (per channel):
    correlation of the padded image with the row-major coefficients, ``clamp(rounded(acc, shift)
    + offset)``. Returns the (H, W[, 3]) image and the saturation flag."""
    K, P = kernel_size, kernel_size//2
    img  = np.asarray(img, np.int64)
    mono = img.ndim == 2
    src  = img[:, :, None] if mono else img
    if bypass:
        return img, 0
    h, w, nc = src.shape
    out = np.zeros((h, w, nc), np.int64)
    sat = 0
    for c in range(nc):
        padded = np_pad_border(src[:, :, c], P, border)
        acc = np.zeros((h, w), np.int64)
        for i in range(K):
            for j in range(K):
                acc += int(coefficients[i*K + j])*padded[i:i + h, j:j + w]
        r = acc if shift == 0 else (acc + (1 << (shift - 1))) >> shift
        y = r + int(offset)
        sat |= int(np.any(y < 0) or np.any(y > (1 << data_width) - 1))
        out[:, :, c] = np.clip(y, 0, (1 << data_width) - 1)
    return (out[:, :, 0] if mono else out), sat

def sobel_model(img, mode="l1", shift=3, border="replicate", data_width=8, with_direction=False, bypass=0):
    """Bit-exact reference for litedsp.image.edge.LiteDSPSobel: gradients from the padded image,
    L1 / L-inf / alpha-max-beta-min magnitude, ``clamp(rounded(mag, shift))`` and the quantised
    direction. Returns the (H, W) magnitude image (and the direction image)."""
    img = np.asarray(img, np.int64)
    h, w = img.shape
    if bypass:
        return (img, np.zeros_like(img)) if with_direction else img
    p = np_pad_border(img, 1, border)
    gx = (p[0:h, 2:] - p[0:h, :w]) + 2*(p[1:h + 1, 2:] - p[1:h + 1, :w]) + (p[2:, 2:] - p[2:, :w])
    gy = (p[2:, 0:w] - p[0:h, 0:w]) + 2*(p[2:, 1:w + 1] - p[0:h, 1:w + 1]) + (p[2:, 2:] - p[0:h, 2:])
    ax, ay = np.abs(gx), np.abs(gy)
    mx, mn = np.maximum(ax, ay), np.minimum(ax, ay)
    mag = {"l1": ax + ay, "linf": mx, "approx": mx + (mn >> 2)}[mode]
    r = mag if shift == 0 else (mag + (1 << (shift - 1))) >> shift
    out = np.clip(r, 0, (1 << data_width) - 1)
    if not with_direction:
        return out
    diag = (mn << 7) > mx*53
    same = (gx < 0) == (gy < 0)
    direction = np.where(diag, np.where(same, 1, 3), np.where(ax > ay, 2, 0))
    return out, direction

def rank_filter_model(img, rank=4, border="replicate", data_width=8, bypass=0):
    """Bit-exact reference for litedsp.image.rank.LiteDSPRankFilter: the ``rank``-th smallest of
    each 3x3 neighbourhood per channel (0 erode, 4 median, 8 dilate)."""
    img = np.asarray(img, np.int64)
    if bypass:
        return img
    mono = img.ndim == 2
    src  = img[:, :, None] if mono else img
    h, w, nc = src.shape
    out = np.zeros_like(src)
    for c in range(nc):
        p = np_pad_border(src[:, :, c], 1, border)
        win = np.stack([p[i:i + h, j:j + w] for i in range(3) for j in range(3)], axis=-1)
        out[:, :, c] = np.sort(win, axis=-1)[:, :, rank]
    return out[:, :, 0] if mono else out

def threshold_model(img, high=128, low=None, invert=0, data_width=8, bypass=0):
    """Bit-exact reference for litedsp.image.point.LiteDSPThreshold: scan-line Schmitt trigger
    (set at >= high, reset below low, state cleared at every line start)."""
    img = np.asarray(img, np.int64)
    if bypass:
        return img
    low = high if low is None else low
    full = (1 << data_width) - 1
    out = np.zeros_like(img)
    for y in range(img.shape[0]):
        state = 0
        for x in range(img.shape[1]):
            v = img[y, x]
            state = 1 if v >= high else (0 if v < low else state)
            out[y, x] = full if (state ^ int(invert)) else 0
    return out

def pixel_gain_model(img, gains, offsets, gain_frac=8, data_width=8, bypass=0):
    """Bit-exact reference for litedsp.image.point.LiteDSPPixelGain: per channel
    ``clamp(rounded(x * gain, gain_frac) + offset)``. Returns the image and the saturation flag."""
    img = np.asarray(img, np.int64)
    if bypass:
        return img, 0
    mono = img.ndim == 2
    src  = img[:, :, None] if mono else img
    out  = np.zeros_like(src)
    sat  = 0
    for c in range(src.shape[2]):
        y = ((src[:, :, c]*int(gains[c]) + (1 << (gain_frac - 1))) >> gain_frac) + int(offsets[c])
        sat |= int(np.any(y < 0) or np.any(y > (1 << data_width) - 1))
        out[:, :, c] = np.clip(y, 0, (1 << data_width) - 1)
    return (out[:, :, 0] if mono else out), sat

def pixel_lut_model(img, tables, bypass=0):
    """Bit-exact reference for litedsp.image.lut.LiteDSPPixelLUT: ``tables`` is one list (shared)
    or one per channel."""
    img = np.asarray(img, np.int64)
    if bypass:
        return img
    if img.ndim == 2:
        return np.asarray(tables[0] if isinstance(tables[0], (list, np.ndarray)) else tables, np.int64)[img]
    out = np.zeros_like(img)
    for c in range(3):
        t = tables[c] if isinstance(tables[0], (list, np.ndarray)) and len(tables) == 3 else (tables[0] if isinstance(tables[0], (list, np.ndarray)) else tables)
        out[:, :, c] = np.asarray(t, np.int64)[img[:, :, c]]
    return out

def color_matrix_model(img, coefficients, in_offsets=(0, 0, 0), out_offsets=(0, 0, 0), coeff_frac=12, data_width=8, bypass=0):
    """Bit-exact reference for litedsp.image.color.LiteDSPColorMatrix: ``clamp(rounded(sum_k m[c][k]
    * (x_k - in_k), frac) + out_c)`` per pixel. Returns the image ((H, W, 3) or (H, W)) and the
    saturation flag."""
    img = np.asarray(img, np.int64)
    if bypass:
        return img, 0
    n_out = len(coefficients)//3
    x = [img[:, :, k] - int(in_offsets[k]) for k in range(3)]
    outs, sat = [], 0
    for c in range(n_out):
        acc = sum(int(coefficients[c*3 + k])*x[k] for k in range(3))
        y = ((acc + (1 << (coeff_frac - 1))) >> coeff_frac) + int(out_offsets[c])
        sat |= int(np.any(y < 0) or np.any(y > (1 << data_width) - 1))
        outs.append(np.clip(y, 0, (1 << data_width) - 1))
    return (outs[0] if n_out == 1 else np.stack(outs, axis=-1)), sat

def debayer_model(raw, pattern="rggb", border="mirror", phase=(0, 0)):
    """Bit-exact reference for litedsp.image.debayer.LiteDSPDebayer: bilinear interpolation on
    the padded mosaic with the colour site from the pixel parity (XOR ``phase`` = (col, row))."""
    from litedsp.image.design import bayer_phase
    raw = np.asarray(raw, np.int64)
    h, w = raw.shape
    p = np_pad_border(raw, 1, border)
    ph = bayer_phase(pattern)
    out = np.zeros((h, w, 3), np.int64)
    for y in range(h):
        for x in range(w):
            rp, cp = (y & 1) ^ phase[1], (x & 1) ^ phase[0]
            site = ph[2*rp + cp]
            red_row = ph[2*rp] == 0 or ph[2*rp + 1] == 0
            c  = p[y + 1, x + 1]
            e4 = (p[y, x + 1] + p[y + 1, x] + p[y + 1, x + 2] + p[y + 2, x + 1] + 2) >> 2
            c4 = (p[y, x] + p[y, x + 2] + p[y + 2, x] + p[y + 2, x + 2] + 2) >> 2
            hh = (p[y + 1, x] + p[y + 1, x + 2] + 1) >> 1
            vv = (p[y, x + 1] + p[y + 2, x + 1] + 1) >> 1
            if site == 0:
                out[y, x] = (c, e4, c4)
            elif site == 2:
                out[y, x] = (c4, e4, c)
            else:
                out[y, x] = (hh, c, vv) if red_row else (vv, c, hh)
    return out

def downscaler_model(img, decimation=2):
    """Bit-exact reference for litedsp.image.scale.LiteDSPDownscaler: rounded box means over
    full D x D tiles (partial edge tiles dropped)."""
    img = np.asarray(img, np.int64)
    D = decimation
    h, w = img.shape[:2]
    th, tw = h//D, w//D
    src = img[:th*D, :tw*D]
    if img.ndim == 2:
        s = src.reshape(th, D, tw, D).sum(axis=(1, 3))
    else:
        s = src.reshape(th, D, tw, D, 3).sum(axis=(1, 3))
    return (s + (D*D)//2) >> (2*int(np.log2(D)))

def crop_model(img, x0=0, y0=0, roi_width=None, roi_height=None):
    """Reference for litedsp.image.scale.LiteDSPCrop: the region of interest."""
    img = np.asarray(img, np.int64)
    roi_width = img.shape[1] - x0 if roi_width is None else roi_width
    roi_height = img.shape[0] - y0 if roi_height is None else roi_height
    return img[y0:y0 + roi_height, x0:x0 + roi_width]

def pixel_stats_model(img, channel=0, zones=4, zone_width=None, zone_height=None):
    """Reference for litedsp.image.stats.LiteDSPPixelStats: frame sum / min / max / count and the
    zone sums (zone index from the pixel position against the zone size, clamped)."""
    img = np.asarray(img, np.int64)
    ch  = img if img.ndim == 2 else img[:, :, channel]
    h, w = ch.shape
    zone_width  = zone_width or max(1, w//zones)
    zone_height = zone_height or max(1, h//zones)
    zsum = [0]*(zones*zones)
    for y in range(h):
        for x in range(w):
            zx, zy = min(zones - 1, x//zone_width), min(zones - 1, y//zone_height)
            zsum[zy*zones + zx] += int(ch[y, x])
    return dict(sum=int(ch.sum()), min=int(ch.min()), max=int(ch.max()), count=w*h, zones=zsum)

def histogram_model(img, channel=0, bins_log2=8, data_width=8):
    """Reference for litedsp.image.histogram.LiteDSPPixelHistogram: counts of the code's top
    ``bins_log2`` bits."""
    img = np.asarray(img, np.int64)
    ch  = img if img.ndim == 2 else img[:, :, channel]
    return np.bincount((ch >> (data_width - bins_log2)).reshape(-1), minlength=1 << bins_log2).astype(np.int64)

def alpha_blend_model(a, b, alpha, data_width=8):
    """Bit-exact reference for litedsp.image.blend.LiteDSPAlphaBlend: ``rounded(alpha * A +
    (256 - alpha) * B, 8)`` with ``alpha`` an int (256 = 1.0) or a mono mask image (full scale
    = 256, else the top 8 bits)."""
    a, b = np.asarray(a, np.int64), np.asarray(b, np.int64)
    if np.ndim(alpha) == 0:
        al = np.full(a.shape[:2], int(alpha), np.int64)
    else:
        m  = np.asarray(alpha, np.int64)
        al = np.where(m == (1 << data_width) - 1, 256, m >> max(0, data_width - 8) if data_width >= 8 else m << (8 - data_width))
    if a.ndim == 3:
        al = al[:, :, None]
    return (al*a + (256 - al)*b + 128) >> 8

def box_overlay_model(img, boxes, thickness=1):
    """Reference for litedsp.image.overlay.LiteDSPBoxOverlay: ``boxes`` = [(x0, y0, x1, y1, color,
    enable)] with inclusive corners and ``color`` a channel tuple (or int for mono); the lowest
    enabled box wins."""
    out = np.asarray(img, np.int64).copy()
    h, w = out.shape[:2]
    for y in range(h):
        for x in range(w):
            for (x0, y0, x1, y1, color, en) in boxes:
                if not en or not (x0 <= x <= x1 and y0 <= y <= y1):
                    continue
                if x - x0 < thickness or x1 - x < thickness or y - y0 < thickness or y1 - y < thickness:
                    out[y, x] = color
                    break
    return out

def angle_modulator_model(x, mode="fm", phase_inc=0, deviation=0, phase_bits=32, data_width=16, lut_depth=1024):
    """Bit-exact reference for litedsp.comm.fm_mod (FM / PM): ``mod = rounded(x * deviation,
    dw - 1)``; FM accumulates ``phase_inc + mod`` per sample, PM adds ``mod`` to the carrier phase;
    cos / sin from the NCO tables addressed by the top bits."""
    addr_bits = int(round(np.log2(lut_depth)))
    cos_t, sin_t = nco_lut(lut_depth, data_width)
    mask = (1 << phase_bits) - 1
    phase = 0
    oi, oq = [], []
    for v in x:
        mod = _rnd(int(v)*int(deviation), data_width - 1)
        if mode == "fm":
            phase = (phase + int(phase_inc) + mod) & mask
            addr_phase = phase
        else:
            phase = (phase + int(phase_inc)) & mask
            addr_phase = (phase + mod) & mask
        addr = addr_phase >> (phase_bits - addr_bits)
        oi.append(int(cos_t[addr])); oq.append(int(sin_t[addr]))
    return np.array(oi, np.int64), np.array(oq, np.int64)

def fm_modulator_model(x, phase_inc=0, deviation=0, phase_bits=32, data_width=16, lut_depth=1024):
    return angle_modulator_model(x, "fm", phase_inc, deviation, phase_bits, data_width, lut_depth)

def pm_modulator_model(x, phase_inc=0, deviation=0, phase_bits=32, data_width=16, lut_depth=1024):
    return angle_modulator_model(x, "pm", phase_inc, deviation, phase_bits, data_width, lut_depth)

def am_modulator_model(x, index=32768, carrier="baseband", phase_inc=0, data_width=16, phase_bits=32, lut_depth=1024):
    """Bit-exact reference for litedsp.comm.am_mod.LiteDSPAMModulator: ``envelope = 2^(dw-2) +
    rounded(x * index, dw)`` (saturated), on I (baseband) or multiplied with the NCO carrier."""
    DW = data_width
    env = [_sat((1 << (DW - 2)) + _rnd(int(v)*int(index), DW), DW) for v in x]
    if carrier == "baseband":
        return np.array(env, np.int64), np.zeros(len(env), np.int64)
    ci, cq = nco_model(phase_inc, len(env), phase_bits, DW, lut_depth)
    oi = [_sat(_rnd(e*int(c), DW - 1), DW) for e, c in zip(env, ci)]
    oq = [_sat(_rnd(e*int(s_), DW - 1), DW) for e, s_ in zip(env, cq)]
    return np.array(oi, np.int64), np.array(oq, np.int64)

def gray_model(words, width=2, n_lanes=1, encode=True):
    """Reference for litedsp.comm.gray: per-lane binary <-> Gray on packed words."""
    mask = (1 << width) - 1
    out = []
    for w in words:
        w = int(w)
        r = 0
        for k in range(n_lanes):
            b = (w >> (k*width)) & mask
            if encode:
                g = b ^ (b >> 1)
            else:
                g = b
                sh = 1
                while sh < width:
                    g ^= g >> sh
                    sh <<= 1
            r |= (g & mask) << (k*width)
        out.append(r)
    return np.array(out, np.int64)

def ssb_modulator_model(x, n_taps=31, sideband=0, data_width=16):
    """Bit-exact reference for litedsp.comm.ssb_mod.LiteDSPSSBModulator: the Hilbert block's two
    FIRs (a unit-delay tap on I, the Hilbert taps on Q) then a saturating negate on Q for the
    lower sideband."""
    from litedsp.filter.design import hilbert_coefficients
    delay = [0]*n_taps
    delay[(n_taps - 1)//2] = (1 << (data_width - 1)) - 1
    i = fir_model(x, delay, data_width)
    q = fir_model(x, hilbert_coefficients(n_taps, data_width=data_width), data_width)
    i, q = np.asarray(i, np.int64), np.asarray(q, np.int64)
    if sideband:
        q = np.where(q == -(1 << (data_width - 1)), (1 << (data_width - 1)) - 1, -q)
    return i, q

def fsk_modulator_model(symbols, bits_per_symbol=1, sps=4, taps=None, deviation=0, phase_inc=0, data_width=16,
    phase_bits=32, lut_depth=1024):
    """Bit-exact reference for litedsp.comm.fsk_mod.LiteDSPFSKModulator: levels ``(2 s - (L-1)) *
    2^(dw-1-bps)`` held for ``sps`` samples, the Gaussian FIR (``taps``, Q1.15) when given, then
    the FM engine."""
    L = 1 << bits_per_symbol
    x = np.repeat([(2*int(s) - (L - 1)) << (data_width - 1 - bits_per_symbol) for s in symbols], sps)
    if taps is not None:
        x = np.asarray(fir_model(x, taps, data_width), np.int64)
    return angle_modulator_model(x, "fm", phase_inc, deviation, phase_bits, data_width, lut_depth)

def line_encode_model(bits, code="nrzi_s", invert=0):
    """Reference for litedsp.comm.line_code.LiteDSPLineEncoder (level / chips start from 0)."""
    out, level = [], 0
    for b in bits:
        b = int(b) & 1
        if code == "nrzi_s":
            level ^= (1 - b); out.append(level)
        elif code == "nrzi_m":
            level ^= b; out.append(level)
        elif code == "manchester":
            out += [b, 1 - b]
        else:
            start = level if b else 1 - level
            out += [start, 1 - start]
            level = 1 - start
    return np.array([v ^ int(invert) for v in out], np.int64)

def line_decode_model(chips, code="nrzi_s", invert=0):
    """Reference for litedsp.comm.line_code.LiteDSPLineDecoder: bits and the violation count."""
    chips = [(int(c) ^ int(invert)) & 1 for c in chips]
    out, level, viol = [], 0, 0
    if code in ("nrzi_s", "nrzi_m"):
        for c in chips:
            changed = c ^ level
            out.append((1 - changed) if code == "nrzi_s" else changed)
            level = c
    else:
        for k in range(0, len(chips) - 1, 2):
            c0, c1 = chips[k], chips[k + 1]
            out.append(c0 if code == "manchester" else 1 - (c0 ^ level))
            viol += int(c0 == c1)
            level = c1
    return np.array(out, np.int64), viol

def conv_interleaver_model(symbols, branches=12, depth=17, deinterleave=False):
    """Reference for litedsp.comm.conv_interleaver: branch j delays by j * depth (or (B-1-j) *
    depth), zero-initialised lines, commutator from branch 0."""
    B = branches
    delays = [(B - 1 - j)*depth if deinterleave else j*depth for j in range(B)]
    lines  = [[0]*d for d in delays]
    out = []
    for k, x in enumerate(symbols):
        j = k % B
        if delays[j] == 0:
            out.append(int(x))
        else:
            out.append(lines[j].pop(0))
            lines[j].append(int(x))
    return np.array(out, np.int64)

def hamming_encode_model(bits, m=3, secded=False):
    """Reference for litedsp.comm.hamming.LiteDSPHammingEncoder on whole blocks of k bits:
    codeword = message, m parity bits (column XOR), optional overall parity."""
    from litedsp.comm.design import hamming_columns, hamming_params
    cols = hamming_columns(m)
    n, k = hamming_params(m, secded)
    out, first, last = [], [], []
    for b in range(len(bits)//k):
        msg = [int(v) & 1 for v in bits[b*k:(b + 1)*k]]
        par = 0
        for i, v in enumerate(msg):
            if v:
                par ^= cols[i]
        cw = msg + [(par >> i) & 1 for i in range(m)]
        if secded:
            cw.append(sum(cw) & 1)
        out += cw
        first += [1] + [0]*(len(cw) - 1)
        last  += [0]*(len(cw) - 1) + [1]
    return np.array(out, np.int64), np.array(first, np.int64), np.array(last, np.int64)

def hamming_decode_model(bits, m=3, secded=False):
    """Reference for litedsp.comm.hamming.LiteDSPHammingDecoder: per block the k message bits
    (single errors corrected, SECDED double errors passed through) and the per-block
    (corrected, uncorrectable) flags."""
    from litedsp.comm.design import hamming_columns, hamming_params
    cols = hamming_columns(m)
    n, k = hamming_params(m, secded)
    nh = (1 << m) - 1
    out, flags = [], []
    for b in range(len(bits)//n):
        cw = [int(v) & 1 for v in bits[b*n:(b + 1)*n]]
        synd = 0
        for i in range(nh):
            if cw[i]:
                synd ^= cols[i]
        q = sum(cw) & 1
        double = bool(secded and synd != 0 and q == 0)
        fixed = list(cw[:nh])
        if synd != 0 and not double:
            fixed[cols.index(synd)] ^= 1
        out += fixed[:k]
        flags.append((int(synd != 0 and not double), int(double)))
    return np.array(out, np.int64), flags
