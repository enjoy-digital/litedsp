#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Pure-Python (build/test time) filter coefficient generators for LiteDSP.

These produce integer coefficients quantized to signed Qm.n for the gateware blocks:
windowed-sinc and Parks-McClellan (Remez) equiripple FIRs, Kaiser spec-driven design,
Butterworth/Chebyshev IIR second-order sections, plus decomposition helpers and realized-
response reporting (the post-quantization numbers commercial tools show). They use NumPy
only (no SciPy) so they run anywhere LiteX builds.
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

# Kaiser Design ------------------------------------------------------------------------------------

def _i0(x):
    """Modified Bessel function of the first kind, order 0 (power series, NumPy only)."""
    x    = np.asarray(x, dtype=float)
    out  = np.ones_like(x)
    term = np.ones_like(x)
    for k in range(1, 128):
        term = term*(x/(2*k))**2
        out  = out + term
        if np.all(term <= 1e-18*out):
            break
    return out

def kaiser_window(n, beta):
    """Kaiser window of length ``n`` with shape parameter ``beta`` (I0 via power series)."""
    check(n >= 1, "expected n >= 1")
    if n == 1:
        return np.ones(1)
    r = 2*np.arange(n)/(n - 1) - 1
    return _i0(beta*np.sqrt(np.maximum(1 - r**2, 0)))/_i0(beta)

def kaiserord(ripple_db, transition_width):
    """Kaiser order/beta estimator for a given spec (Kaiser's empirical formulas).

    ``ripple_db`` is the desired stopband attenuation / passband ripple in positive dB
    (``-20*log10(delta)``), ``transition_width`` the transition band in normalized frequency
    (cycles/sample). Returns ``(n_taps, beta)``.
    """
    a = float(ripple_db)
    if a > 50:
        beta = 0.1102*(a - 8.7)
    elif a > 21:
        beta = 0.5842*(a - 21)**0.4 + 0.07886*(a - 21)
    else:
        beta = 0.0
    n_taps = int(np.ceil((a - 7.95)/(14.36*transition_width))) + 1
    return n_taps, beta

def firwin_kaiser(f_cutoff, ripple_db, transition_width, data_width=None):
    """Kaiser-windowed-sinc low-pass FIR designed from a spec instead of a tap count.

    ``f_cutoff`` is the -6 dB cutoff in normalized frequency (0..0.5), ``ripple_db`` the
    stopband attenuation in positive dB, ``transition_width`` the transition band width.
    The length/beta come from :func:`kaiserord` (length forced odd for a Type-I filter).
    Returns float taps (unity DC gain), or signed Q1.(N-1) integers if ``data_width`` given.
    """
    n_taps, beta = kaiserord(ripple_db, transition_width)
    n_taps += (n_taps % 2 == 0)  # Force odd (Type-I symmetric).
    m = np.arange(n_taps) - (n_taps - 1)/2
    h = np.sinc(2*f_cutoff*m)*kaiser_window(n_taps, beta)
    h = h/h.sum()
    if data_width is None:
        return h
    return quantize(h, data_width - 1, data_width)

# Parks-McClellan (Remez Exchange) Design ----------------------------------------------------------

def _bary_eval(x, xk, gamma, yk):
    """Barycentric Lagrange interpolation of the points ``(xk, yk)`` evaluated at ``x``."""
    d = np.asarray(x)[:, None] - xk[None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        c = gamma/d
        y = (c @ yk)/c.sum(axis=1)
    # Points that coincide with a node: take the node value directly.
    hit = np.abs(d) < 1e-14
    for i in np.nonzero(hit.any(axis=1))[0]:
        y[i] = yk[np.argmin(np.abs(d[i]))]
    return y

def remez(n_taps, bands, desired, weights=None, n_grid=16, max_iter=40):
    """Parks-McClellan equiripple (minimax) linear-phase FIR design, NumPy only.

    Remez exchange over a dense frequency grid: Chebyshev alternation with barycentric
    Lagrange interpolation of the cosine-basis amplitude, supporting Type-I (odd ``n_taps``)
    and Type-II (even ``n_taps``) symmetric filters.

    Parameters
    ----------
    n_taps  : filter length.
    bands   : flat sequence of band edges in normalized frequency (0..0.5), 2 per band, e.g.
              ``[0, f_pass, f_stop, 0.5]`` for a low-pass.
    desired : desired gain per band (``len(bands)//2`` values).
    weights : relative error weight per band (default all 1).
    n_grid  : grid density (grid points per approximating function).

    Returns float taps (``np.ndarray`` of length ``n_taps``).
    """
    bands   = np.asarray(bands, dtype=float).reshape(-1, 2)
    desired = np.asarray(desired, dtype=float)
    weights = np.ones(len(bands)) if weights is None else np.asarray(weights, dtype=float)
    check(len(desired) == len(bands),  "expected one desired gain per band")
    check(len(weights) == len(bands),  "expected one weight per band")
    check(np.all(np.diff(bands.ravel()) >= 0) and bands[0][0] >= 0 and bands[-1][1] <= 0.5,
        "expected monotonic band edges in 0..0.5")
    odd = (n_taps % 2 == 1)
    r   = (n_taps + 1)//2 if odd else n_taps//2  # Cosine-basis size.
    check(odd or not (bands[-1][1] >= 0.5 and desired[-1] != 0),
        "even n_taps forces a zero at Nyquist; use odd n_taps for this response")
    # Dense frequency grid (band edges always included).
    df = 0.5/(n_grid*r)
    grid, dgrid, wgrid = [], [], []
    for (f0, f1), d, w in zip(bands, desired, weights):
        if not odd:
            f1 = min(f1, 0.5 - 0.5*df)  # Type-II amplitude has a structural zero at Nyquist.
        n_pts = max(int(np.ceil((f1 - f0)/df)) + 1, 2)
        f = np.linspace(f0, f1, n_pts)
        grid.append(f)
        dgrid.append(np.full(n_pts, d))
        wgrid.append(np.full(n_pts, w))
    seg_edges = np.cumsum([0] + [len(g) for g in grid])  # Segment boundaries in the flat grid.
    grid  = np.concatenate(grid)
    dgrid = np.concatenate(dgrid)
    wgrid = np.concatenate(wgrid)
    if not odd:  # Type-II: A(f) = cos(pi f) P(f); approximate P against D/cos with W*cos.
        c     = np.cos(np.pi*grid)
        dgrid = dgrid/c
        wgrid = wgrid*c
    x = np.cos(2*np.pi*grid)
    check(len(grid) > r + 1, "grid too coarse; increase n_grid")
    # Remez exchange loop.
    idx = np.unique(np.round(np.linspace(0, len(grid) - 1, r + 1)).astype(int))
    sgn = (-1.0)**np.arange(r + 1)
    xk = gamma = ak = None
    for _ in range(max_iter):
        xk = x[idx]
        # Barycentric weights of the current reference set.
        gamma = np.array([1.0/np.prod(xk[k] - np.delete(xk, k)) for k in range(r + 1)])
        delta = np.sum(gamma*dgrid[idx])/np.sum(gamma*sgn/wgrid[idx])
        ak    = dgrid[idx] - sgn*delta/wgrid[idx]
        error = wgrid*(_bary_eval(x, xk, gamma, ak) - dgrid)
        # Candidate extrema: local min/max of the error within each band, plus band edges.
        cand = set(seg_edges[:-1]) | set(seg_edges[1:] - 1)
        for s0, s1 in zip(seg_edges[:-1], seg_edges[1:]):
            de = np.diff(error[s0:s1])
            cand |= set(s0 + 1 + np.nonzero(de[:-1]*de[1:] <= 0)[0])
        # Enforce alternation: merge same-sign runs (keep the largest), then trim endpoints.
        alt = []
        for i in sorted(cand):
            if alt and (error[i] >= 0) == (error[alt[-1]] >= 0):
                if abs(error[i]) > abs(error[alt[-1]]):
                    alt[-1] = i
            else:
                alt.append(i)
        while len(alt) > r + 1:
            alt.pop(0 if abs(error[alt[0]]) < abs(error[alt[-1]]) else -1)
        if len(alt) < r + 1:
            break  # Degenerate (over-determined) problem: keep the last reference set.
        new_idx = np.array(alt)
        emax    = np.max(np.abs(error[new_idx]))
        if np.array_equal(new_idx, idx) or (emax - abs(delta)) <= 1e-6*emax:
            idx = new_idx
            break
        idx = new_idx
    # Reconstruct taps: sample the final interpolant at f = j/n_taps and inverse-DFT.
    fj = np.arange(n_taps//2 + 1)/n_taps
    aj = _bary_eval(np.cos(2*np.pi*fj), xk, gamma, ak)
    if not odd:
        aj = aj*np.cos(np.pi*fj)
    H = np.zeros(n_taps, dtype=complex)
    H[:len(fj)] = aj*np.exp(-1j*np.pi*np.arange(len(fj))*(n_taps - 1)/n_taps)
    H[len(fj):] = np.conj(H[1:n_taps - len(fj) + 1][::-1])
    h = np.fft.ifft(H).real
    return 0.5*(h + h[::-1])  # Enforce exact symmetry.

def remez_lowpass(n_taps, f_pass, f_stop, data_width=None):
    """Equiripple low-pass FIR via :func:`remez`; ``f_pass``/``f_stop`` normalized (0..0.5).

    Returns float taps, or signed Q1.(N-1) integers if ``data_width`` is given.
    """
    check(0 < f_pass < f_stop <= 0.5, "expected 0 < f_pass < f_stop <= 0.5")
    h = remez(n_taps, [0, f_pass, f_stop, 0.5], [1.0, 0.0])
    if data_width is None:
        return h
    return quantize(h, data_width - 1, data_width)

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

def _zpk_to_sos(zeros, poles, f_ref, g_ref):
    """Bilinear-transform analog zeros/poles (already frequency-prewarped) into digital SOS.

    Zeros at infinity are implied (``len(poles) - len(zeros)`` of them; they map to z = -1).
    The overall gain is pinned so ``|H(exp(2j*pi*f_ref))| = g_ref``, distributed evenly
    across sections for dynamic range. Returns float rows ``[b0, b1, b2, 1.0, a1, a2]``
    (ready for :func:`biquad_sos_quantize`).
    """
    zd = [(1 + s)/(1 - s) for s in zeros] + [-1.0 + 0j]*(len(poles) - len(zeros))
    pd = [(1 + s)/(1 - s) for s in poles]
    def split(roots):
        # Real roots, and one representative per conjugate pair (sorted by angle).
        real = sorted(r.real for r in roots if abs(r.imag) <= 1e-9)
        cplx = sorted((r for r in roots if r.imag > 1e-9), key=np.angle)
        return real, cplx
    zr, zc = split(zd)
    pr, pc = split(pd)
    sections = []
    for k, p in enumerate(pc):  # Conjugate pole pairs (paired with conjugate zero pairs by angle).
        a1, a2 = -2*p.real, abs(p)**2
        if k < len(zc):
            z = zc[k]
            b = [1.0, -2*z.real, abs(z)**2]
        else:
            z0, z1 = zr.pop(), zr.pop()
            b = [1.0, -(z0 + z1), z0*z1]
        sections.append([b[0], b[1], b[2], 1.0, a1, a2])
    for p in pr:                # Real poles (first-order sections).
        b = [1.0, -zr.pop(), 0.0] if zr else [1.0, 0.0, 0.0]
        sections.append([b[0], b[1], b[2], 1.0, -p, 0.0])
    sections.sort(key=lambda s: s[5])  # Low-Q first (poles closest to the unit circle last).
    # Even gain distribution: every section gets |H_i(f_ref)| = g_ref**(1/n_sections).
    zi = np.exp(-2j*np.pi*f_ref)  # z^-1 at the reference frequency.
    for s in sections:
        g = abs((s[0] + s[1]*zi + s[2]*zi**2)/(1 + s[4]*zi + s[5]*zi**2))
        scale = g_ref**(1/len(sections))/g
        s[0], s[1], s[2] = scale*s[0], scale*s[1], scale*s[2]
    return sections

def butterworth_sos(order, f_cutoff, btype="lowpass"):
    """Butterworth digital filter as float second-order sections (bilinear transform).

    ``f_cutoff`` is the -3 dB frequency in normalized frequency (0..0.5); ``btype`` is
    ``"lowpass"`` or ``"highpass"``. Returns float rows ``[b0, b1, b2, 1.0, a1, a2]``
    feeding :func:`biquad_sos_quantize`.
    """
    check(btype in ("lowpass", "highpass"), "expected btype in (lowpass, highpass)")
    check(0 < f_cutoff < 0.5, "expected 0 < f_cutoff < 0.5")
    theta = np.pi*(2*np.arange(order) + 1)/(2*order)
    poles = -np.sin(theta) + 1j*np.cos(theta)  # Left-half-plane, |p| = 1.
    wc    = np.tan(np.pi*f_cutoff)             # Bilinear prewarp.
    if btype == "lowpass":
        return _zpk_to_sos([], list(wc*poles), f_ref=0.0, g_ref=1.0)
    return _zpk_to_sos([0j]*order, list(wc/poles), f_ref=0.5, g_ref=1.0)

def chebyshev1_sos(order, ripple_db, f_cutoff):
    """Chebyshev type-I low-pass (``ripple_db`` passband ripple) as float SOS.

    ``f_cutoff`` is the passband edge (gain = -ripple_db there) in normalized frequency.
    Returns float rows ``[b0, b1, b2, 1.0, a1, a2]`` feeding :func:`biquad_sos_quantize`.
    """
    check(0 < f_cutoff < 0.5, "expected 0 < f_cutoff < 0.5")
    eps   = np.sqrt(10**(ripple_db/10) - 1)
    mu    = np.arcsinh(1/eps)/order
    theta = np.pi*(2*np.arange(order) + 1)/(2*order)
    poles = -np.sinh(mu)*np.sin(theta) + 1j*np.cosh(mu)*np.cos(theta)
    poles = np.tan(np.pi*f_cutoff)*poles
    g_dc  = 1.0 if order % 2 else 10**(-ripple_db/20)  # Even orders dip -ripple_db at DC.
    return _zpk_to_sos([], list(poles), f_ref=0.0, g_ref=g_dc)

def chebyshev2_sos(order, atten_db, f_cutoff):
    """Chebyshev type-II (inverse Chebyshev) low-pass as float SOS.

    ``f_cutoff`` is the stopband edge in normalized frequency; the stopband floor beyond it
    is ``-atten_db`` (equiripple), the passband monotonic with unity DC gain. Returns float
    rows ``[b0, b1, b2, 1.0, a1, a2]`` feeding :func:`biquad_sos_quantize`.
    """
    check(0 < f_cutoff < 0.5, "expected 0 < f_cutoff < 0.5")
    eps   = 1/np.sqrt(10**(atten_db/10) - 1)
    mu    = np.arcsinh(1/eps)/order
    theta = np.pi*np.arange(-order + 1, order, 2)/(2*order)
    poles = -np.exp(1j*theta)
    poles = 1/(np.sinh(mu)*poles.real + 1j*np.cosh(mu)*poles.imag)
    zeros = -1j/np.sin(theta[np.abs(np.sin(theta)) > 1e-12])  # Odd order: middle zero at inf.
    wc    = np.tan(np.pi*f_cutoff)
    return _zpk_to_sos(list(wc*zeros), list(wc*poles), f_ref=0.0, g_ref=1.0)

# Response Reporting -------------------------------------------------------------------------------

def freq_response(taps, n_points=1024, data_width=None):
    """Magnitude response of the *actual* FIR taps, quantization included.

    ``taps`` are floats, or signed Q1.(``data_width``-1) integers when ``data_width`` is
    given (as produced by the designers here) — the response then reflects the quantized
    coefficients the gateware really uses. Returns ``(freqs, H_db)`` with ``freqs`` in
    normalized frequency 0..0.5.
    """
    taps = np.asarray(taps, dtype=float)
    if data_width is not None:
        taps = taps/(1 << (data_width - 1))
    freqs = np.linspace(0, 0.5, n_points)
    H     = np.exp(-2j*np.pi*np.outer(freqs, np.arange(len(taps)))) @ taps
    return freqs, 20*np.log10(np.maximum(np.abs(H), 1e-12))

def report(taps, f_pass, f_stop, data_width=None, n_points=4096):
    """Realized low-pass figures of merit (what commercial tools show after quantization).

    Returns ``{"passband_ripple_db", "stopband_atten_db", "dc_gain_db"}`` measured on the
    actual (optionally quantized, see :func:`freq_response`) coefficients: peak-to-peak
    ripple over ``f <= f_pass``, worst-case attenuation over ``f >= f_stop``, and DC gain.
    """
    freqs, h_db = freq_response(taps, n_points=n_points, data_width=data_width)
    passband = h_db[freqs <= f_pass]
    stopband = h_db[freqs >= f_stop]
    return {
        "passband_ripple_db": float(passband.max() - passband.min()),
        "stopband_atten_db":  float(-stopband.max()),
        "dc_gain_db":         float(h_db[0]),
    }

def sos_freq_response(sections, frac_bits=None, n_points=1024):
    """Magnitude response of cascaded biquad sections (float or quantized).

    ``sections`` are float rows ``[b0, b1, b2, a0, a1, a2]`` (as from the ``*_sos``
    designers), or integer dicts ``{b0,b1,b2,a1,a2}`` in Q?.``frac_bits`` (as from
    :func:`biquad_sos_quantize`) when ``frac_bits`` is given. Returns ``(freqs, H_db)``.
    """
    freqs = np.linspace(0, 0.5, n_points)
    zi    = np.exp(-2j*np.pi*freqs)  # z^-1.
    H     = np.ones(n_points, dtype=complex)
    for s in sections:
        if isinstance(s, dict):
            b0, b1, b2, a1, a2 = s["b0"], s["b1"], s["b2"], s["a1"], s["a2"]
        else:
            b0, b1, b2, a0, a1, a2 = s
            b0, b1, b2, a1, a2 = b0/a0, b1/a0, b2/a0, a1/a0, a2/a0
        if frac_bits is not None:
            b0, b1, b2, a1, a2 = (v/(1 << frac_bits) for v in (b0, b1, b2, a1, a2))
        H = H*(b0 + b1*zi + b2*zi**2)/(1 + a1*zi + a2*zi**2)
    return freqs, 20*np.log10(np.maximum(np.abs(H), 1e-12))
