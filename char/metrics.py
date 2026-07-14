#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Pure-NumPy DSP quality measurement library (SFDR/ENOB/IMD3/ripple/droop/...).

Signal-quality equivalents of the impl/ resource metrics: each function turns raw sample
arrays (from the golden models in test/models.py or a simulation capture) into one
datasheet-grade number. Two measurement styles are used:

- Windowed-FFT metrics (SFDR, IMD3, image rejection) apply a Hann window and integrate
  ``guard`` bins around each tone, so they work on non-coherent (non-bin-aligned) tones.
- Fit-based metrics (SINAD/ENOB, tone amplitude, noise floor) least-squares fit a tone at
  the *known* frequency and measure the residual; no window or coherence needed.
"""

import numpy as np

# Windowed-FFT Helpers -------------------------------------------------------------------------------

def _band_idx(n, k, guard):
    """FFT bin indices in ``[k-guard, k+guard]`` with wraparound (negative frequencies)."""
    return np.arange(k - guard, k + guard + 1) % n

def _power_spectrum(x):
    """Hann-windowed FFT power spectrum of a real or complex array."""
    x = np.asarray(x)
    return np.abs(np.fft.fft(x*np.hanning(len(x))))**2

def _band_power(p, f, guard):
    """Integrated power of the tone at normalized frequency ``f`` (bin ± guard, leakage-safe)."""
    n = len(p)
    return float(p[_band_idx(n, int(round(f*n)), guard)].sum())

# SFDR -----------------------------------------------------------------------------------------------

def sfdr_db(x, guard=16):
    """Spurious-free dynamic range (dB): fundamental power vs the largest spur.

    Hann-windowed FFT; the fundamental is the strongest non-DC band. DC (windowed leakage)
    and, for real inputs, the fundamental's negative-frequency image are excluded from the
    spur search with the same ±``guard`` bins, and the spur band is summed on the masked
    spectrum so the fundamental's leakage skirt never counts as a spur.
    """
    x = np.asarray(x)
    n = len(x)
    p = _power_spectrum(x)
    mask = np.ones(n, bool)
    mask[_band_idx(n, 0, guard)] = False
    k0   = int(np.argmax(np.where(mask, p, 0)))
    fund = p[_band_idx(n, k0, guard)].sum()
    mask[_band_idx(n, k0, guard)] = False
    if not np.iscomplexobj(x):
        mask[_band_idx(n, n - k0, guard)] = False   # Conjugate image is part of the signal.
    pm   = np.where(mask, p, 0.0)
    ks   = int(np.argmax(pm))
    spur = pm[_band_idx(n, ks, guard)].sum()
    return 10*np.log10(fund/spur)

# Sine-Fit SINAD / ENOB / Amplitude / Noise Floor ----------------------------------------------------

def _tone_fit(x, f):
    """Least-squares fit of a tone at normalized frequency ``f`` (+ DC) to ``x``.

    Returns ``(amplitude, signal_power, residual)``; ``residual`` is noise + distortion.
    Real arrays fit ``a*cos + b*sin + c``, complex arrays fit ``a*exp(2j*pi*f*n) + c``.
    """
    x = np.asarray(x)
    n = np.arange(len(x))
    if np.iscomplexobj(x):
        basis = np.column_stack([np.exp(2j*np.pi*f*n), np.ones(len(x))])
        coef, *_ = np.linalg.lstsq(basis, x, rcond=None)
        amp, psig = np.abs(coef[0]), np.abs(coef[0])**2
    else:
        basis = np.column_stack([np.cos(2*np.pi*f*n), np.sin(2*np.pi*f*n), np.ones(len(x))])
        coef, *_ = np.linalg.lstsq(basis, np.asarray(x, float), rcond=None)
        amp, psig = np.hypot(coef[0], coef[1]), (coef[0]**2 + coef[1]**2)/2
    return float(amp), float(psig), x - basis @ coef

def sinad_db(x, f):
    """Signal-to-noise-and-distortion ratio (dB) of the tone at known frequency ``f``."""
    _, psig, resid = _tone_fit(x, f)
    return 10*np.log10(psig/np.mean(np.abs(resid)**2))

def enob_bits(x, f):
    """Effective number of bits from the sine-fit SINAD: ``(SINAD - 1.76)/6.02``.

    Uses the full-scale-sine convention; feed a (near) full-scale tone for absolute ENOB.
    """
    return (sinad_db(x, f) - 1.76)/6.02

def tone_amplitude(x, f):
    """Least-squares amplitude of the tone at known normalized frequency ``f``."""
    return _tone_fit(x, f)[0]

def noise_floor_dbfs(x, f, full_scale):
    """Total noise + distortion power (tone at ``f`` removed by sine fit) in dBFS.

    Referenced to a full-scale sine of amplitude ``full_scale`` (power ``full_scale**2/2``).
    """
    _, _, resid = _tone_fit(x, f)
    return 10*np.log10(np.mean(np.abs(resid)**2)/(full_scale**2/2))

# IMD3 / Image Rejection -----------------------------------------------------------------------------

def imd3_db(x, f1, f2, guard=8):
    """Two-tone 3rd-order intermodulation (dBc): mean tone power vs the strongest product.

    The products measured are ``2*f1 - f2`` and ``2*f2 - f1`` (Hann-windowed FFT).
    """
    p = _power_spectrum(x)
    tones    = (_band_power(p, f1, guard) + _band_power(p, f2, guard))/2
    products = max(_band_power(p, 2*f1 - f2, guard), _band_power(p, 2*f2 - f1, guard))
    return 10*np.log10(tones/products)

def image_rejection_db(x, f_signal, f_image, guard=8):
    """Power ratio (dB) between the wanted tone at ``f_signal`` and its image at ``f_image``."""
    p = _power_spectrum(x)
    return 10*np.log10(_band_power(p, f_signal, guard)/_band_power(p, f_image, guard))

# Frequency Response (Linear Blocks) -----------------------------------------------------------------

def freq_response(model_fn, n_points=4096, amplitude=(1 << 15) - 1):
    """Complex frequency response of a linear block via impulse -> rFFT.

    ``model_fn`` maps an integer sample array to the block's integer output (e.g. a
    ``fir_model`` closure), so the response includes coefficient quantization *and* output
    rounding. Returns ``(f, H)`` with ``f`` in cycles/sample (0..0.5).
    """
    x    = np.zeros(n_points, np.int64)
    x[0] = amplitude
    y    = np.asarray(model_fn(x), float)/amplitude
    return np.fft.rfftfreq(n_points), np.fft.rfft(y)

def passband_ripple_db(f, H, f_pass):
    """Peak-to-peak magnitude ripple (dB) over the passband ``f <= f_pass``."""
    mag = 20*np.log10(np.abs(H[f <= f_pass]))
    return float(mag.max() - mag.min())

def stopband_atten_db(f, H, f_stop):
    """Minimum stopband attenuation (dB, positive) over ``f >= f_stop``, vs the peak gain."""
    mag = 20*np.log10(np.abs(H) + 1e-300)
    return float(mag.max() - mag[f >= f_stop].max())

# CIC Droop ------------------------------------------------------------------------------------------

def cic_droop_db(R, N, M, f):
    """Theoretical CIC droop (dB, <= 0) at input-rate normalized frequency ``f``.

    ``|H(f)| = (sin(pi*f*R*M)/(R*M*sin(pi*f)))**N`` normalized to unity at DC.
    """
    f   = np.asarray(f, float)
    num = np.sin(np.pi*f*R*M)
    den = R*M*np.sin(np.pi*f)
    h   = np.abs(np.divide(num, den, out=np.ones_like(num), where=(den != 0)))
    out = 20*N*np.log10(h)
    return float(out) if out.ndim == 0 else out

# Settling -------------------------------------------------------------------------------------------

def settling_time_samples(x, target, tol=0.05):
    """First index after which ``x`` stays within ``target ± tol*target`` (never: ``len(x)``)."""
    outside = np.abs(np.asarray(x, float) - target) > tol*abs(target)
    return int(np.nonzero(outside)[0][-1]) + 1 if outside.any() else 0

# Window Sidelobes -----------------------------------------------------------------------------------

def sidelobe_level_db(w, oversample=64):
    """Peak sidelobe level (dB below the mainlobe, positive) of a window shape ``w``.

    Zero-padded rFFT; the mainlobe ends at the first spectral null (first local minimum).
    """
    w   = np.asarray(w, float)
    mag = np.abs(np.fft.rfft(w, len(w)*oversample))
    k   = 1
    while k < len(mag) - 1 and mag[k + 1] < mag[k]:
        k += 1
    return 20*np.log10(mag[0]/mag[k:].max())
