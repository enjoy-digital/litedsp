#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side radar / sonar design math (NumPy only, not re-exported): CFAR threshold factors,
tracking gains, array steering weights, TVG laws and unit conversions in the fixed-point formats
of the blocks."""

import math

import numpy as np

from litedsp.common import check

DB_PER_LOG2 = 20*math.log10(2)                                     # 6.0206 dB per log2 unit.

# CFAR ---------------------------------------------------------------------------------------------

def cfar_alpha(pfa=1e-4, n_train_cells=16, domain="power", frac_bits=8):
    """Threshold factor applied to the training-cell *mean* by the CFAR blocks, as a Q.frac_bits
    integer. ``domain="power"``: exact CA-CFAR on exponential (square-law) cells,
    ``alpha = N * (pfa**(-1/N) - 1)``. ``domain="magnitude"``: Rayleigh envelope cells,
    asymptotic ``alpha = sqrt(-4 ln(pfa) / pi)`` (the finite-N loss is small for N >= 16)."""
    check(0.0 < pfa < 1.0, "expected 0 < pfa < 1")
    check(n_train_cells >= 1, "expected n_train_cells >= 1")
    check(domain in ("power", "magnitude"), "expected domain in ('power', 'magnitude')")
    if domain == "power":
        alpha = n_train_cells*(pfa**(-1.0/n_train_cells) - 1.0)
    else:
        alpha = math.sqrt(-4.0*math.log(pfa)/math.pi)
    return int(round(alpha*(1 << frac_bits)))

# Tracking -----------------------------------------------------------------------------------------

def alpha_beta_from_index(tracking_index=0.5):
    """Kalata's optimal ``(alpha, beta)`` for a tracking index ``lambda = sigma_w T**2 /
    sigma_v`` (process to measurement noise ratio)."""
    check(tracking_index > 0.0, "expected tracking_index > 0")
    lam = tracking_index
    r = (4.0 + lam - math.sqrt(8.0*lam + lam*lam))/4.0
    alpha = 1.0 - r*r
    beta  = 2.0*(2.0 - alpha) - 4.0*math.sqrt(1.0 - alpha)
    return alpha, beta

def tracker_gains(alpha=0.5, beta=0.15, gain_frac=8):
    """Quantise ``(alpha, beta)`` to the tracker's unsigned Q1.gain_frac words."""
    check(0.0 < alpha <= 1.0 and 0.0 <= beta <= 2.0, "expected 0 < alpha <= 1, 0 <= beta <= 2")
    lim = (1 << (gain_frac + 1)) - 1
    return min(lim, int(round(alpha*(1 << gain_frac)))), min(lim, int(round(beta*(1 << gain_frac))))

# Beamforming --------------------------------------------------------------------------------------

def steering_weights(n_elements=4, angle_deg=0.0, d_over_lambda=0.5, taper="rect", weight_frac=14):
    """Narrowband phase-shift weights for a uniform linear array steered to ``angle_deg`` from
    broadside: ``w[e] = taper[e] * exp(-j 2 pi d/lambda e sin(theta)) / n_elements``.
    Returns ``(real, imag)`` integer lists in signed Q(2).weight_frac."""
    check(n_elements >= 1, "expected n_elements >= 1")
    from litedsp.radar.waveform import window_taper
    taper_v = window_taper(taper, n_elements)
    e = np.arange(n_elements)
    w = taper_v*np.exp(-2j*math.pi*d_over_lambda*e*math.sin(math.radians(angle_deg)))/n_elements
    lim = (1 << (weight_frac + 1)) - 1
    q = lambda v: [int(max(-lim, min(lim, round(float(x)*(1 << weight_frac))))) for x in v]
    return q(w.real), q(w.imag)

# Units --------------------------------------------------------------------------------------------

def range_bin_metres(sample_rate, propagation_speed=299792458.0):
    """Range extent of one bin: ``c / (2 fs)`` (use the speed of sound for sonar)."""
    return propagation_speed/(2.0*sample_rate)

def doppler_bin_velocity(bin_index, n_pulses, prf, wavelength):
    """Radial velocity of Doppler bin ``bin_index`` (natural FFT order: bins ``>= n_pulses/2``
    are negative frequencies): ``f_d * wavelength / 2``."""
    k = bin_index if bin_index < n_pulses/2 else bin_index - n_pulses
    return k*prf/n_pulses*wavelength/2.0

# Sonar TVG ----------------------------------------------------------------------------------------

def tvg_coefficients(db_per_decade=40.0, alpha_db_per_bin=0.0, g0_db=0.0, gain_frac=8):
    """``(g0, k_log, k_lin)`` words for :class:`LiteDSPTVG`'s log2-domain gain law
    ``log2(gain) = g0 + k_log*log2(r) + k_lin*r`` (Q.gain_frac): spreading loss
    ``db_per_decade * log10(r)`` (40 = two-way spherical) plus absorption ``alpha_db_per_bin *
    r`` plus a fixed ``g0_db``."""
    k_log = db_per_decade/20.0                                     # log10(r) = log2(r)*log10(2).
    k_lin = alpha_db_per_bin/DB_PER_LOG2
    g0    = g0_db/DB_PER_LOG2
    q = lambda v: int(round(v*(1 << gain_frac)))
    return q(g0), q(k_log), q(k_lin)
