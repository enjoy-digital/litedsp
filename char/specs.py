#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-block characterization plans: stimulus + measurement -> datasheet quality metrics.

All measurements run on the NumPy golden models from ``test/models.py`` (except the CORDIC,
which has no standalone model and is measured through a Migen simulation via
``test/common.py``). The golden models are held bit-exact — or SNR-equivalent where rounding
legitimately differs — against the RTL by the co-simulation tests in ``test/`` and
``sim/``, so the numbers measured here characterize the gateware itself while keeping the
characterization sweep fast and deterministic (pure NumPy, fixed stimulus, no toolchain).

Each spec function returns ``{metric_name: value}``. ``DIRECTIONS`` tells the budget gate
which way a change is a violation: ``"min"`` metrics (SFDR, ENOB, attenuation, rejection,
IMD3, sidelobe level) must not drop below the baseline, ``"max"`` metrics (ripple, droop
error, settling time, steady-state error, noise floor) must not rise above it.
"""

import numpy as np

from litedsp.filter.design   import firwin_lowpass
from litedsp.analysis.window import window_coefficients

from char import metrics

from test.models import (nco_model, mixer_model, fir_model, cic_decimator_model, agc_model,
    clipper_model, window_model, magnitude_model, dc_blocker_model)

FULL_SCALE = (1 << 15) - 1                     # 16-bit signed full scale.

# NCO ------------------------------------------------------------------------------------------------

NCO_LUT_EXACT_INCS = [
    (1 << 32)//64,                             # Bin-aligned, LUT-exact addressing (f = 1/64).
    301 << 22,                                 # LUT-exact, visits all 1024 entries (f = 301/1024).
]
NCO_WORST_INCS = [
    0x01234567,                                # Arbitrary increment.
    0x0fffffff,                                # Near fs/16, maximal phase-truncation activity.
    ((1 << 32)//64) + (1 << 14),               # Near-rational: truncation-spur beat at fs/256.
    ((1 << 32)//3) + 1,                        # Near fs/3.
    int((1 << 32)*0.30103),                    # Irrational-ish.
]

def spec_nco():
    """NCO (lut_depth=1024, phase_bits=32, 16-bit I/Q): worst case over a phase_inc sweep.

    Two regimes: LUT-exact increments (multiples of 2^(phase_bits - addr_bits)) show the
    amplitude-quantization limit; generic increments are phase-truncation limited (worst
    spur ~ -6.02 dB per LUT address bit, i.e. ~-60 dBc for a 1024-deep LUT).
    """
    n = 8192
    def measure(incs):
        sfdr, enob, nf = [], [], []
        for inc in incs:
            i, q = nco_model(inc, n)
            x    = i + 1j*q
            f    = inc/(1 << 32)
            sfdr.append(metrics.sfdr_db(x))
            enob.append(metrics.enob_bits(x, f))
            nf.append(metrics.noise_floor_dbfs(x, f, FULL_SCALE))
        return min(sfdr), min(enob), max(nf)
    sfdr_exact, _, _      = measure(NCO_LUT_EXACT_INCS)
    sfdr, enob, nf        = measure(NCO_LUT_EXACT_INCS + NCO_WORST_INCS)
    return {
        "sfdr_lut_exact_db" : sfdr_exact,
        "sfdr_db"           : sfdr,
        "enob_bits"         : enob,
        "noise_floor_dbfs"  : nf,
    }

# CORDIC ---------------------------------------------------------------------------------------------

def spec_cordic():
    """CORDIC rotation (16-bit data/angle, 16 stages): ENOB of a rotated full-circle tone.

    No standalone NumPy model exists (the test compares against ideal trigonometry), so this
    runs the Migen simulation directly — same stimulus as ``test_cordic.test_sincos``.
    """
    from litedsp.generation.cordic import LiteDSPCORDIC

    from test.common import run_stream, column

    dw = aw = 16
    amp = 30000
    dut = LiteDSPCORDIC(data_width=dw, angle_width=aw, mode="rotation", with_csr=False)
    zs  = np.linspace(-(1 << (aw - 1)), (1 << (aw - 1)) - 1, 256).astype(int)
    samples = [{"x": amp, "y": 0, "z": int(z)} for z in zs]
    cap = run_stream(dut, samples, len(zs), ["x", "y", "z"], ["x", "y"],
        sink_throttle=0.0, source_ready_rate=1.0)
    got   = column(cap, "x", dw).astype(float) + 1j*column(cap, "y", dw).astype(float)
    ref   = amp*np.exp(1j*(zs/(1 << aw)*2*np.pi))
    sinad = 10*np.log10(np.sum(np.abs(ref)**2)/np.sum(np.abs(got - ref)**2))
    return {"enob_bits": (sinad - 1.76)/6.02}

# Mixer ----------------------------------------------------------------------------------------------

def spec_mixer():
    """Mixer down-conversion with a quadrature LO: rejection of the f_sig + f_lo image.

    The LO is a LUT-exact NCO tone (no phase truncation), so the measurement isolates the
    mixer's own quadrature accuracy (LO quantization + complex-multiply rounding) from the
    NCO spurs characterized separately. The rejection is rounding-noise-floor limited.
    """
    n      = 8192
    f_sig  = 0.123
    amp    = 25000
    lo_inc = (1 << 32)//64
    f_lo   = lo_inc/(1 << 32)
    t      = np.arange(n)
    a_i    = np.round(amp*np.cos(2*np.pi*f_sig*t)).astype(np.int64)
    a_q    = np.round(amp*np.sin(2*np.pi*f_sig*t)).astype(np.int64)
    b_i, b_q = nco_model(lo_inc, n)
    o_i, o_q = mixer_model(a_i, a_q, b_i, b_q, mode="down")
    x = o_i + 1j*o_q
    return {"image_rejection_db": metrics.image_rejection_db(x, f_sig - f_lo, f_sig + f_lo)}

# FIR ------------------------------------------------------------------------------------------------

def spec_fir():
    """FIR low-pass (firwin_lowpass(63, 0.2), quantized Q1.15 taps): realized mask numbers.

    Passband edge 0.15, stopband edge 0.25 (cutoff 0.2, Hamming transition ~0.05). The
    impulse-response measurement includes tap quantization and output rounding.
    """
    taps = firwin_lowpass(63, 0.2, data_width=16)
    f, H = metrics.freq_response(lambda x: fir_model(x, taps), n_points=4096)
    return {
        "passband_ripple_db" : metrics.passband_ripple_db(f, H, f_pass=0.15),
        "stopband_atten_db"  : metrics.stopband_atten_db(f, H, f_stop=0.25),
    }

# CIC ------------------------------------------------------------------------------------------------

CIC_RATES  = (4, 8, 16)                        # Decimation R.
CIC_STAGES = (3, 4)                            # n_stages N (diff_delay M = 1).

def spec_cic():
    """CIC decimator: worst passband droop error vs theory, per (R, N) configuration.

    Tone sweep over the output passband (f_out in 0.05..0.25); each measured amplitude drop
    is compared against ``(sin(pi*f*R)/(R*sin(pi*f)))**N``. The metric is the max absolute
    deviation in dB, i.e. how faithfully the fixed-point datapath realizes the ideal CIC.
    """
    out   = {}
    amp   = 20000
    f_out = np.linspace(0.05, 0.25, 5)
    for R in CIC_RATES:
        for N in CIC_STAGES:
            errs = []
            for fo in f_out:
                fi = fo/R
                x  = np.round(amp*np.sin(2*np.pi*fi*np.arange((256 + 16)*R))).astype(np.int64)
                y  = cic_decimator_model(x, R, N)[16:]     # Skip the filter transient.
                meas   = 20*np.log10(metrics.tone_amplitude(y, fo)/amp)
                theory = metrics.cic_droop_db(R, N, 1, fi)
                errs.append(abs(meas - theory))
            out[f"droop_err_r{R}_n{N}_db"] = max(errs)
    return out

# AGC ------------------------------------------------------------------------------------------------

def spec_agc():
    """AGC (mu=8, gain_frac=8): settling to a 4x level step + steady-state error.

    Constant-envelope tone at 25% of the target level; the magnitude observable is the
    block's own alpha-max-beta-min estimate, boxcar-smoothed over ~2 tone periods to remove
    the estimator's phase ripple. Settling = within ±5% of target.
    """
    n           = 4096
    f           = 0.0731
    amp, target = 4000, 16000
    t    = np.arange(n)
    i    = np.round(amp*np.cos(2*np.pi*f*t)).astype(np.int64)
    q    = np.round(amp*np.sin(2*np.pi*f*t)).astype(np.int64)
    o_i, o_q = agc_model(i, q, target)
    mag  = magnitude_model(o_i, o_q).astype(float)
    mag  = np.convolve(mag, np.ones(32)/32, mode="valid")  # ~2.3 tone periods.
    tail = mag[len(mag)//2:]
    return {
        "settling_samples"       : float(metrics.settling_time_samples(mag, target, tol=0.05)),
        "steady_state_error_pct" : abs(tail.mean() - target)/target*100,
    }

# Clipper --------------------------------------------------------------------------------------------

def spec_clipper():
    """Clipper at 50% clip depth (threshold = half the two-tone peak): IMD3."""
    n      = 8192
    f1, f2 = 0.101, 0.117
    amp    = 12000
    t      = np.arange(n)
    x      = np.round(amp*(np.sin(2*np.pi*f1*t) + np.sin(2*np.pi*f2*t))).astype(np.int64)
    o_i, _ = clipper_model(x, np.zeros(n, np.int64), threshold=amp)
    return {"imd3_dbc": metrics.imd3_db(o_i.astype(float), f1, f2)}

# DC Blocker -------------------------------------------------------------------------------------------

DC_REJECTION_CAP_DB = 140.0                    # Report cap: the residual can be exactly 0.

def spec_dc_blocker():
    """DC blocker high-precision notch (pole_shift=5, precision_bits=8): DC rejection.

    Full-scale DC step (0.95 FS) + -30 dBFS tone at f = 1/64; the residual is |mean| of the
    settled output over whole tone periods. The documented worst-case bound is
    -6.02*(data_width - 1 + p - pole_shift) = -108.4 dBFS; the away-from-zero leak (no
    deadband) + error-feedback requantization (DC-free) leave a measured residual of exactly
    0 here, so the metric is capped at 140 dB.
    """
    n = 16384
    t = np.arange(n)
    x = 31000 + np.round(1000*np.cos(2*np.pi*t/64)).astype(np.int64)
    y = dc_blocker_model(x, pole_shift=5, data_width=16, precision_bits=8)
    residual = abs(y[n//2:].mean())            # LSBs of DC left; tail = 128 whole tone periods.
    if residual == 0:
        return {"dc_rejection_db": DC_REJECTION_CAP_DB}
    return {"dc_rejection_db": min(DC_REJECTION_CAP_DB, -20*np.log10(residual/(1 << 15)))}

# Window ---------------------------------------------------------------------------------------------

def spec_window():
    """Window block (hann, n=64): peak sidelobe level after quantization + output rounding."""
    n      = 64
    coeffs = window_coefficients(n, "hann", data_width=16)
    o_i, _ = window_model(np.full(n, FULL_SCALE, np.int64), np.zeros(n, np.int64), coeffs)
    return {"sidelobe_level_db": metrics.sidelobe_level_db(o_i.astype(float))}

# Registry -------------------------------------------------------------------------------------------

SPECS = {
    "nco"     : spec_nco,
    "cordic"  : spec_cordic,
    "mixer"   : spec_mixer,
    "fir"     : spec_fir,
    "cic"     : spec_cic,
    "agc"        : spec_agc,
    "clipper"    : spec_clipper,
    "dc_blocker" : spec_dc_blocker,
    "window"     : spec_window,
}

DIRECTIONS = {
    "nco"     : {"sfdr_lut_exact_db": "min", "sfdr_db": "min", "enob_bits": "min",
                 "noise_floor_dbfs": "max"},
    "cordic"  : {"enob_bits": "min"},
    "mixer"   : {"image_rejection_db": "min"},
    "fir"     : {"passband_ripple_db": "max", "stopband_atten_db": "min"},
    "cic"     : {f"droop_err_r{R}_n{N}_db": "max" for R in CIC_RATES for N in CIC_STAGES},
    "agc"        : {"settling_samples": "max", "steady_state_error_pct": "max"},
    "clipper"    : {"imd3_dbc": "min"},
    "dc_blocker" : {"dc_rejection_db": "min"},
    "window"     : {"sidelobe_level_db": "min"},
}

DESCRIPTIONS = {
    "nco"     : "NCO/DDS, `lut_depth=1024`, `phase_bits=32`, 16-bit I/Q; 8192-sample records. "
                "`sfdr_lut_exact_db` uses LUT-exact increments (amplitude-quantization limit); the "
                "other metrics are the worst case over a 7-point `phase_inc` sweep including "
                "near-rational/irrational-ish increments, where performance is phase-truncation "
                "limited (~6 dB per LUT address bit).",
    "cordic"  : "CORDIC rotation mode, 16-bit data/angle, 16 stages (Migen simulation). ENOB of a "
                "0.92 FS tone rotated through a full circle (256 angles).",
    "mixer"   : "Complex mixer, down-conversion of a 0.76 FS tone at f=0.123 with a LUT-exact "
                "quadrature NCO LO at f=1/64; rejection of the f_sig+f_lo image (isolates mixer "
                "arithmetic; rounding-noise-floor limited).",
    "fir"     : "FIR low-pass `firwin_lowpass(63, 0.2)` quantized to Q1.15. Realized response of "
                "the quantized taps (impulse -> FFT); passband f<=0.15, stopband f>=0.25.",
    "cic"     : "CIC decimator, `diff_delay=1`, 16-bit. Max |measured - theoretical| droop over "
                "the output passband (f_out 0.05..0.25) per (decimation R, n_stages N).",
    "agc"     : "AGC, `mu=8`, `gain_frac=8`. Constant-envelope tone at 25% of target: samples to "
                "settle within +-5% of target, and residual level error (alpha-max-beta-min "
                "magnitude, boxcar-smoothed).",
    "clipper" : "Clipper at 50% clip depth (threshold = half the two-tone peak). Two tones at "
                "f=0.101/0.117: 3rd-order intermodulation distortion of the clipped output.",
    "window"  : "Window block, hann, n=64, 16-bit coefficients. Peak sidelobe level of the "
                "realized (quantized, rounded) window shape.",
    "dc_blocker": "DC blocker, high-precision notch (`pole_shift=5`, `precision_bits=8`, 16-bit). "
                "0.95 FS DC step + -30 dBFS tone at f=1/64: rejection of the steady-state DC "
                "residual (|mean| over 128 settled tone periods). Worst-case bound "
                "-6.02*(15 + p - pole_shift) = -108.4 dBFS; the measured residual is exactly 0 "
                "(no leak deadband, DC-free error-feedback requantizer), so the metric reports "
                "the 140 dB cap.",
}

def unit(metric):
    """Display unit for a metric, derived from its name suffix."""
    for suffix, u in [("_dbfs", "dBFS"), ("_dbc", "dBc"), ("_db", "dB"),
                      ("_bits", "bits"), ("_samples", "samples"), ("_pct", "%")]:
        if metric.endswith(suffix):
            return u
    return "-"
