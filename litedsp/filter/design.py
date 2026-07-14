#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Pure-Python (build/test time) filter coefficient generators for LiteDSP.

These produce integer coefficients quantized to signed Qm.n for the gateware blocks, and a
few decomposition helpers. They use NumPy only (no SciPy) so they run anywhere LiteX builds.
"""

import numpy as np

from litedsp.common import check

# Quantization -------------------------------------------------------------------------------------

def quantize(coeffs, frac_bits, coeff_width=16):
    """Quantize float coefficients to signed integers in Q?.frac_bits, clamped to coeff_width."""
    scale = 1 << frac_bits
    lo    = -(1 << (coeff_width - 1))
    hi    =  (1 << (coeff_width - 1)) - 1
    return [int(max(lo, min(hi, round(c*scale)))) for c in coeffs]

# FIR Design ---------------------------------------------------------------------------------------

def _window(n, name):
    k = np.arange(n)
    if name == "rect":
        return np.ones(n)
    if name == "hann":
        return 0.5 - 0.5*np.cos(2*np.pi*k/(n - 1))
    if name == "hamming":
        return 0.54 - 0.46*np.cos(2*np.pi*k/(n - 1))
    if name == "blackman":
        return 0.42 - 0.5*np.cos(2*np.pi*k/(n - 1)) + 0.08*np.cos(4*np.pi*k/(n - 1))
    raise ValueError(f"Unknown window: {name}")

def firwin_lowpass(n_taps, cutoff, window="hamming", data_width=16, gain=1.0):
    """Windowed-sinc low-pass FIR, ``cutoff`` in normalized freq (0..0.5), unity DC gain.

    Returns signed Q1.(N-1) integer taps (length ``n_taps``).
    """
    m = np.arange(n_taps) - (n_taps - 1)/2
    h = np.sinc(2*cutoff*m)*_window(n_taps, window)
    h = gain*h/h.sum()
    return quantize(h, data_width - 1, data_width)

def firwin_bandpass(n_taps, f_low, f_high, window="hamming", data_width=16, gain=1.0):
    """Windowed-sinc band-pass FIR; ``f_low``/``f_high`` normalized (0..0.5), unity gain at center.

    Ideal band-pass = lowpass(f_high) - lowpass(f_low), windowed and normalized so the magnitude
    at the band center is ``gain``. Returns signed Q1.(N-1) integer taps (length ``n_taps``).
    """
    check(0 <= f_low < f_high <= 0.5, "expected 0 <= f_low < f_high <= 0.5")
    m = np.arange(n_taps) - (n_taps - 1)/2
    h = (2*f_high*np.sinc(2*f_high*m) - 2*f_low*np.sinc(2*f_low*m))*_window(n_taps, window)
    fc   = 0.5*(f_low + f_high)
    resp = np.hypot(np.sum(h*np.cos(2*np.pi*fc*m)), np.sum(h*np.sin(2*np.pi*fc*m)))
    if resp != 0:
        h = gain*h/resp
    return quantize(h, data_width - 1, data_width)

def rrc_coefficients(sps, span, beta, data_width=16, gain=1.0):
    """Root-raised-cosine FIR. ``sps`` samples/symbol, ``span`` symbols, rolloff ``beta``.

    Returns signed Q1.(N-1) integer taps (length ``sps*span + 1``), normalized to unit energy.
    """
    n = sps*span + 1
    t = (np.arange(n) - (n - 1)/2)/sps
    h = np.zeros(n)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-8:
            h[i] = 1 - beta + 4*beta/np.pi
        elif beta > 0 and abs(abs(4*beta*ti) - 1) < 1e-8:
            h[i] = (beta/np.sqrt(2))*((1 + 2/np.pi)*np.sin(np.pi/(4*beta)) +
                                      (1 - 2/np.pi)*np.cos(np.pi/(4*beta)))
        else:
            num = np.sin(np.pi*ti*(1 - beta)) + 4*beta*ti*np.cos(np.pi*ti*(1 + beta))
            den = np.pi*ti*(1 - (4*beta*ti)**2)
            h[i] = num/den
    h = gain*h/np.sqrt(np.sum(h**2))
    return quantize(h, data_width - 1, data_width)

def hilbert_coefficients(n_taps, window="hamming", data_width=16):
    """Type-III Hilbert transformer FIR (antisymmetric, even taps zero). Odd ``n_taps``."""
    check(n_taps % 2 == 1, "Hilbert FIR length must be odd.")
    m = np.arange(n_taps) - (n_taps - 1)//2
    h = np.zeros(n_taps)
    for i, mi in enumerate(m):
        h[i] = 0.0 if (mi % 2 == 0) else 2.0/(np.pi*mi)
    h *= _window(n_taps, window)
    return quantize(h, data_width - 1, data_width)

def cic_comp_coefficients(n_taps, R, N, M=1, data_width=16, cutoff=0.2, frac_bits=None):
    """CIC droop-compensation FIR (inverse-sinc over the passband).

    Least-squares fit of a symmetric (linear-phase) FIR to ``1/|H_cic(f)|`` over the output
    passband ``f in [0, cutoff]`` (output-rate normalized). Odd ``n_taps``. The center tap
    exceeds 1.0 (inverse-sinc), so coefficients use Q2.(N-2) by default (``frac_bits =
    data_width-2``); instantiate the compensation FIR with ``shift=frac_bits``.
    """
    if frac_bits is None:
        frac_bits = data_width - 2
    check(n_taps % 2 == 1, "CIC compensation FIR length must be odd.")
    half = n_taps//2
    f    = np.linspace(0, cutoff, 8*n_taps)
    # CIC droop at the *output* rate: |sin(pi f)/(pi f)|^N near band-center, normalized.
    fr = f/R  # Map output-rate freq back to input-rate for the sinc argument.
    with np.errstate(divide="ignore", invalid="ignore"):
        hc = np.abs(np.sin(np.pi*M*R*fr)/(M*R*np.sin(np.pi*fr)))**N
    hc[0]   = 1.0
    desired = 1.0/hc
    # Symmetric FIR basis: H(f) = h0 + sum_{d=1..half} 2*h_d*cos(2*pi*f*d).
    A = np.zeros((len(f), half + 1))
    A[:, 0] = 1.0
    for d in range(1, half + 1):
        A[:, d] = 2*np.cos(2*np.pi*f*d)
    p, *_ = np.linalg.lstsq(A, desired, rcond=None)
    h = np.empty(n_taps)
    h[half] = p[0]
    for d in range(1, half + 1):
        h[half + d] = h[half - d] = p[d]
    h = h/h.sum()  # Unity DC gain.
    return quantize(h, frac_bits, data_width)

def halfband_coefficients(n_taps, window="hamming", data_width=16, gain=1.0):
    """Half-band low-pass FIR (cutoff 0.25): even taps are ~zero, center ~0.5. Odd ``n_taps``."""
    check(n_taps % 2 == 1, "expected n_taps % 2 == 1")
    return firwin_lowpass(n_taps, 0.25, window=window, data_width=data_width, gain=gain)

# Decomposition ------------------------------------------------------------------------------------

def polyphase_split(taps, n_phases):
    """Split ``taps`` into ``n_phases`` polyphase sub-filters: phase[p] = taps[p::n_phases]."""
    taps = list(taps)
    if len(taps) % n_phases:
        taps = taps + [0]*(n_phases - (len(taps) % n_phases))
    return [taps[p::n_phases] for p in range(n_phases)]

# IIR Design ---------------------------------------------------------------------------------------

def biquad_sos_quantize(sos, coeff_width=18, frac_bits=14):
    """Quantize biquad second-order sections to integer coefficients.

    ``sos`` is a list of sections ``[b0, b1, b2, a0, a1, a2]`` (a0 normalized to 1, as from
    SciPy ``butter(..., output='sos')``). Returns ``(sections, frac_bits)`` where each section
    is a dict of signed integer ``b0,b1,b2,a1,a2`` in Q?.frac_bits.
    """
    out = []
    for s in sos:
        b0, b1, b2, a0, a1, a2 = s
        b0, b1, b2, a1, a2 = (np.array([b0, b1, b2, a1, a2])/a0).tolist()
        q = quantize([b0, b1, b2, a1, a2], frac_bits, coeff_width)
        out.append({"b0": q[0], "b1": q[1], "b2": q[2], "a1": q[3], "a2": q[4]})
    return out, frac_bits
