#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Declarative Verilator co-simulation specs: one entry per cosim-eligible block.

``SPECS`` covers exactly the blocks marked ``cosim=True`` in ``test/registry.py`` (enforced by
:func:`check_coverage`, called by the runner). Each spec function returns
``(dut, cols, n_out, model)``. Framed cases append ``(sink_tags, source_tags)``; cases with
runtime controls append a final tuple of control Signals, whose per-sample columns follow all
stream columns:

- ``dut``   : the block, built with ``with_csr=False``; controls are set through reset values
              (``signal.reset = value``), so they need no top-level ports.
- ``cols``  : stimulus columns, one per sink payload field, sinks in discovery order
              (``litedsp.flow.metadata._ports``: sorted names, fields in layout order);
              when ``sink_tags`` is true, each sink's ``first`` and ``last`` columns follow
              its payload fields; empty for source-only blocks (NCO).
- ``n_out`` : number of output samples to capture (kept a few short of the steady-state total
              so the run terminates on an exact count).
- ``model`` : ``model(cols) -> [expected output columns]`` (bit-exact NumPy golden model from
              ``test/models.py``), one array (>= n_out long) per source payload field and,
              when ``source_tags`` is true, the source ``first`` and ``last`` arrays.
"""

import random

import numpy as np

from test import models

# Stimulus -----------------------------------------------------------------------------------------

def _rand_cols(n_cols, n, lo=-20000, hi=20000, seed=1):
    prng = random.Random(seed)
    return [[prng.randint(lo, hi) for _ in range(n)] for _ in range(n_cols)]

def _conv_symbols(bits, constraint=7, polys=(0o171, 0o133)):
    """Small deterministic convolutional-encoder stimulus helper (same bit order as RTL)."""
    state, mask, out = 0, (1 << (constraint - 1)) - 1, []
    for bit in bits:
        full = int(bit) | (state << 1)
        out.append(sum(((g & full).bit_count() & 1) << k for k, g in enumerate(polys)))
        state = full & mask
    return out

# Generation ---------------------------------------------------------------------------------------

def spec_nco():
    from litedsp.generation.nco import LiteDSPNCO
    n, phase_inc = 256, 0x01234567
    dut = LiteDSPNCO(data_width=16, with_csr=False)
    dut.phase_inc.reset = phase_inc
    return dut, [], n, lambda c: list(models.nco_model(phase_inc, n))

def spec_cordic_rot():
    from litedsp.generation.cordic import LiteDSPCORDIC
    n    = 300
    dut  = LiteDSPCORDIC(data_width=16, angle_width=16, mode="rotation", with_csr=False)
    cols = _rand_cols(2, n, lo=-20000, hi=20000) + _rand_cols(1, n, lo=-32768, hi=32767, seed=2)
    def model(c):                                                     # sink(x, y, z).
        out = [models.cordic_rotation_model(x, y, z) for x, y, z in zip(c[0], c[1], c[2])]
        return [np.array([o[0] for o in out]), np.array([o[1] for o in out])]
    return dut, cols, n - 4, model

# Mixing -------------------------------------------------------------------------------------------

def spec_mixer():
    from litedsp.mixing.mixer import LiteDSPMixer
    n    = 360
    dut  = LiteDSPMixer(data_width=16, with_csr=False)             # mode reset = 0 (down).
    cols = _rand_cols(4, n)                                        # sink_a(i,q), sink_b(i,q).
    # After the random down-conversion payload has drained, zero-valued guard/input regions
    # exercise up-conversion and both bypass mux arms without making configuration-boundary
    # timing part of the sample-by-sample numerical contract.
    for c in cols:
        c[240:] = [0]*(n - 240)
    mode   = [int(k >= 264) for k in range(n)]
    bypass = [0 if k < 296 else (1 if k < 328 else 2) for k in range(n)]
    return dut, cols + [mode, bypass], n - 4, \
        lambda c: list(models.mixer_model(c[0], c[1], c[2], c[3])), \
        False, False, (dut.mode, dut.bypass)

def _spec_carrier_loop(detector, architecture="classic"):
    from litedsp.comm.pll import LiteDSPCarrierLoop
    n = 280
    dut = LiteDSPCarrierLoop(data_width=16, detector=detector, kp_shift=6, ki_shift=14,
        architecture=architecture, with_csr=False)
    cols = _rand_cols(2, n, lo=-14000, hi=14000,
        seed={"pll": 101, "bpsk": 103, "qpsk": 107}[detector])
    return dut, cols, n - 4, lambda c: list(models.carrier_loop_model(
        c[0], c[1], detector=detector, kp_shift=6, ki_shift=14,
        loop_delay=dut.loop_delay))

def spec_carrier_loop():
    return _spec_carrier_loop("pll")

def spec_carrier_loop_bpsk():
    return _spec_carrier_loop("bpsk")

def spec_carrier_loop_qpsk():
    return _spec_carrier_loop("qpsk")

def spec_carrier_loop_qpsk_pipelined():
    return _spec_carrier_loop("qpsk", architecture="pipelined")

def _spec_timing_recovery(ted="mm", architecture="classic"):
    from litedsp.comm.timing_recovery import LiteDSPTimingRecovery
    n = 720
    dut = LiteDSPTimingRecovery(data_width=16, sps=2, gain_mu=0.1, ted=ted,
        architecture=architecture, with_csr=False)
    cols = _rand_cols(2, n, lo=-14000, hi=14000,
        seed=211 + 7*(ted == "gardner"))
    ref = models.timing_recovery_model(cols[0], cols[1], ted=ted)
    # Leave a short tail so the generic randomized-ready harness never depends on the exact
    # end-of-input drain cycle while still checking every adaptive slip in the main sequence.
    n_out = len(ref[0]) - 2
    return dut, cols, n_out, lambda c: list(models.timing_recovery_model(c[0], c[1], ted=ted))

def spec_timing_recovery():
    return _spec_timing_recovery()

def spec_timing_recovery_pipelined():
    return _spec_timing_recovery(architecture="pipelined")

def spec_timing_recovery_gardner():
    return _spec_timing_recovery(ted="gardner")

def spec_timing_recovery_gardner_pipelined():
    return _spec_timing_recovery(ted="gardner", architecture="pipelined")

# Filter -------------------------------------------------------------------------------------------

def spec_fir_real():
    from litedsp.filter.fir    import LiteDSPFIRFilter
    from litedsp.filter.design import firwin_lowpass
    n, n_taps = 200, 17
    coeffs = firwin_lowpass(n_taps, 0.2)
    dut = LiteDSPFIRFilter(n_taps=n_taps, data_width=16)
    for t, c in enumerate(coeffs):
        dut.coeffs[t].reset = int(c)
    cols = _rand_cols(1, n)
    return dut, cols, n - 8, lambda c: [models.fir_model(np.array(c[0]), coeffs)]

def spec_fir_complex():
    from litedsp.filter.fir    import LiteDSPFIRFilterComplex
    from litedsp.filter.design import firwin_lowpass
    n, n_taps = 200, 17
    coeffs = firwin_lowpass(n_taps, 0.2)
    dut  = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=16, coefficients=coeffs, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 8, lambda c: list(models.fir_complex_model(c[0], c[1], coeffs))

def spec_fir_complex_pipelined():
    from litedsp.filter.fir    import LiteDSPFIRFilterComplex
    from litedsp.filter.design import firwin_lowpass
    n, n_taps = 200, 33
    coeffs = firwin_lowpass(n_taps, 0.2)
    dut = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=16, coefficients=coeffs,
        with_csr=False, architecture="pipelined")
    cols = _rand_cols(2, n)
    return dut, cols, n - 12, lambda c: list(models.fir_complex_model(c[0], c[1], coeffs))

def spec_fir_decimator():
    from litedsp.filter.fir_poly import LiteDSPFIRDecimator
    from litedsp.filter.design   import firwin_lowpass
    n, n_taps, R = 256, 16, 8
    coeffs = firwin_lowpass(n_taps, 0.4/R)
    dut  = LiteDSPFIRDecimator(n_taps=n_taps, decimation=R, data_width=16,
        coefficients=coeffs, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n//R - 2, lambda c: [models.fir_decimator_model(c[0], coeffs, R),
                                           models.fir_decimator_model(c[1], coeffs, R)]

def spec_fir_decimator_pipelined():
    from litedsp.filter.fir_poly import LiteDSPFIRDecimator
    from litedsp.filter.design   import firwin_lowpass
    n, n_taps, R = 256, 17, 8
    coeffs = firwin_lowpass(n_taps, 0.4/R)
    dut = LiteDSPFIRDecimator(n_taps=n_taps, decimation=R, data_width=16,
        coefficients=coeffs, with_csr=False, architecture="pipelined")
    cols = _rand_cols(2, n)
    return dut, cols, n//R - 2, lambda c: [models.fir_decimator_model(c[0], coeffs, R),
                                           models.fir_decimator_model(c[1], coeffs, R)]

def spec_fir_interpolator():
    from litedsp.filter.fir_poly import LiteDSPFIRInterpolator
    from litedsp.filter.design   import firwin_lowpass
    n, n_taps, L = 48, 16, 8
    coeffs = firwin_lowpass(n_taps, 0.4/L, gain=L)                 # Gain L offsets zero-stuff loss.
    dut  = LiteDSPFIRInterpolator(n_taps=n_taps, interpolation=L, data_width=16,
        coefficients=coeffs, with_csr=False)
    cols = _rand_cols(2, n, lo=-8000, hi=8000)
    return dut, cols, n*L - 8, lambda c: [models.fir_interpolator_model(c[0], coeffs, L),
                                          models.fir_interpolator_model(c[1], coeffs, L)]

def spec_fir_interpolator_pipelined():
    from litedsp.filter.fir_poly import LiteDSPFIRInterpolator
    from litedsp.filter.design   import firwin_lowpass
    n, n_taps, L = 48, 17, 8
    coeffs = firwin_lowpass(n_taps, 0.4/L, gain=L)
    dut = LiteDSPFIRInterpolator(n_taps=n_taps, interpolation=L, data_width=16,
        coefficients=coeffs, with_csr=False, architecture="pipelined")
    cols = _rand_cols(2, n, lo=-8000, hi=8000)
    return dut, cols, n*L - 8, lambda c: [models.fir_interpolator_model(c[0], coeffs, L),
                                          models.fir_interpolator_model(c[1], coeffs, L)]

def spec_cic_decimator():
    from litedsp.filter.cic import LiteDSPCICDecimator
    n, R, N = 512, 8, 3
    dut  = LiteDSPCICDecimator(data_width=16, decimation=R, n_stages=N,
        with_csr=False, staged=True)
    cols = _rand_cols(2, n)
    return dut, cols, n//R - 4, lambda c: [models.cic_decimator_model(np.array(c[0]), R, N),
                                           models.cic_decimator_model(np.array(c[1]), R, N)]

def spec_cic_interpolator():
    from litedsp.filter.cic import LiteDSPCICInterpolator
    n, R, N = 64, 8, 3
    dut  = LiteDSPCICInterpolator(data_width=16, interpolation=R, n_stages=N,
        with_csr=False, staged=True)
    cols = _rand_cols(2, n)
    return dut, cols, n*R - 2*R, lambda c: [models.cic_interpolator_model(np.array(c[0]), R, N),
                                            models.cic_interpolator_model(np.array(c[1]), R, N)]

def spec_iir_biquad():
    from litedsp.filter.iir_biquad import LiteDSPIIRBiquad
    from litedsp.filter.design     import biquad_sos_quantize
    n  = 300
    w0, alpha, cw = 2*np.pi*0.1, np.sin(2*np.pi*0.1)/(2*0.707), np.cos(2*np.pi*0.1)
    sos = [(1 - cw)/2, 1 - cw, (1 - cw)/2, 1 + alpha, -2*cw, 1 - alpha]  # RBJ low-pass fc=0.1.
    secs, frac = biquad_sos_quantize([sos], frac_bits=14)
    dut  = LiteDSPIIRBiquad(data_width=16, coefficients=secs[0], frac_bits=frac, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.iir_biquad_model(c[0], secs[0], frac),
                                        models.iir_biquad_model(c[1], secs[0], frac)]

def spec_dc_blocker():
    from litedsp.filter.dc_blocker import LiteDSPDCBlocker
    n    = 300
    dut  = LiteDSPDCBlocker(data_width=16, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.dc_blocker_model(np.array(c[0])),
                                        models.dc_blocker_model(np.array(c[1]))]

def spec_moving_average():
    from litedsp.filter.moving_average import LiteDSPMovingAverage
    n, length_log2 = 300, 4
    dut  = LiteDSPMovingAverage(data_width=16, length_log2=length_log2, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.moving_average_model(np.array(c[0]), length_log2),
                                        models.moving_average_model(np.array(c[1]), length_log2)]

def spec_equalizer():
    from litedsp.filter.equalizer import LiteDSPLMSEqualizer, MODE_TRAINED, MODE_CMA, MODE_DD
    n, n_taps, mu_shift, cma_egain = 1200, 7, 16, 6
    cma_r2, dd_level = round(2*7000*7000/(1 << 15)), 7000
    dut = LiteDSPLMSEqualizer(n_taps=n_taps, data_width=16, mu_shift=mu_shift,
        cma_egain=cma_egain,
        architecture="pipelined", update_pipeline=True, with_csr=False)
    cols = _rand_cols(4, n, lo=-8000, hi=8000, seed=71)
    mode = [MODE_TRAINED if k < 300 else MODE_CMA if k < 600 else MODE_DD if k < 900
            else MODE_TRAINED for k in range(n)]
    train = [int(not 1000 <= k < 1050) for k in range(n)]
    return dut, cols + [train, mode, [cma_r2]*n, [dd_level]*n], n - 8, \
        lambda c: list(models.equalizer_model(
        c[0], c[1], c[2], c[3], n_taps=n_taps, data_width=16, mu_shift=mu_shift,
        cma_egain=cma_egain, mode=c[5], cma_r2=cma_r2, dd_level=dd_level, train=c[4],
        adaptation_delay=9)), False, False, (dut.train, dut.mode, dut.cma_r2, dut.dd_level)

def spec_pfb_channelizer():
    from litedsp.mixing.pfb_channelizer import LiteDSPPFBChannelizer
    from litedsp.filter.design import firwin_lowpass
    M, T, n = 4, 4, 64
    coeffs = firwin_lowpass(M*T, 0.4/M)
    dut  = LiteDSPPFBChannelizer(n_channels=M, taps_per_channel=T, data_width=16,
        coefficients=coeffs, with_csr=False)
    cols = _rand_cols(2, n, seed=67)
    first = [int(k % M == 0) for k in range(n)]
    last  = [int(k % M == M - 1) for k in range(n)]
    return dut, cols, n, lambda c: [
        *models.pfb_channelizer_model(c[0], c[1], coeffs, M), first, last], False, True

def spec_pfb_channelizer_fft():
    from litedsp.mixing.pfb_channelizer import LiteDSPPFBChannelizer
    from litedsp.filter.design import firwin_lowpass
    M, T, n = 16, 2, 64
    coeffs = firwin_lowpass(M*T, 0.4/M)
    dut = LiteDSPPFBChannelizer(n_channels=M, taps_per_channel=T, data_width=16,
        coefficients=coeffs, architecture="fft", with_csr=False)
    cols  = _rand_cols(2, n, seed=69)
    first = [int(k % M == 0) for k in range(n)]
    last  = [int(k % M == M - 1) for k in range(n)]
    return dut, cols, n, lambda c: [
        *models.pfb_channelizer_fft_model(c[0], c[1], coeffs, M), first, last], False, True

def spec_pfb_channelizer_2x():
    from litedsp.mixing.pfb_channelizer import LiteDSPPFBChannelizer
    from litedsp.filter.design import firwin_lowpass
    M, T, n = 4, 4, 32
    coeffs = firwin_lowpass(M*T, 0.4/M)
    dut = LiteDSPPFBChannelizer(n_channels=M, taps_per_channel=T, data_width=16,
        coefficients=coeffs, oversampling=2, with_csr=False)
    cols = _rand_cols(2, n, seed=73)
    n_out = 2*n
    first = [int(k % M == 0) for k in range(n_out)]
    last  = [int(k % M == M - 1) for k in range(n_out)]
    return dut, cols, n_out, lambda c: [
        *models.pfb_channelizer_model(c[0], c[1], coeffs, M, oversampling=2), first, last], \
        False, True

def spec_pfb_channelizer_fft_2x():
    from litedsp.mixing.pfb_channelizer import LiteDSPPFBChannelizer
    from litedsp.filter.design import firwin_lowpass
    M, T, n = 16, 2, 64
    coeffs = firwin_lowpass(M*T, 0.4/M)
    dut = LiteDSPPFBChannelizer(n_channels=M, taps_per_channel=T, data_width=16,
        coefficients=coeffs, architecture="fft", oversampling=2, with_csr=False)
    cols = _rand_cols(2, n, seed=79)
    n_out = 2*n
    first = [int(k % M == 0) for k in range(n_out)]
    last  = [int(k % M == M - 1) for k in range(n_out)]
    return dut, cols, n_out, lambda c: [
        *models.pfb_channelizer_fft_model(c[0], c[1], coeffs, M, oversampling=2), first, last], \
        False, True

# Rate ---------------------------------------------------------------------------------------------

def spec_downsampler():
    from litedsp.rate.dropper import LiteDSPDownsampler
    n, R = 300, 3
    dut  = LiteDSPDownsampler(data_width=16, with_csr=False)
    dut.factor.reset = R                                           # Runtime factor via reset.
    cols = _rand_cols(2, n)
    return dut, cols, n//R - 4, lambda c: [models.decimate_model(c[0], R),
                                           models.decimate_model(c[1], R)]

def spec_upsampler():
    from litedsp.rate.dropper import LiteDSPUpsampler
    n, L = 64, 4
    dut  = LiteDSPUpsampler(data_width=16, with_csr=False)         # zero_stuff=False: repeat mode.
    dut.factor.reset = L                                           # Runtime factor via reset.
    cols = _rand_cols(2, n)
    return dut, cols, n*L - 8, lambda c: [models.interpolate_model(c[0], L),
                                          models.interpolate_model(c[1], L)]

# Level --------------------------------------------------------------------------------------------

def spec_gain():
    from litedsp.level.gain import LiteDSPGain
    n, gain = 300, 0x7000                                           # 1.75 in Q2.14.
    dut = LiteDSPGain(data_width=16, with_csr=False)
    dut.gain.reset  = gain
    cols = _rand_cols(2, n)
    shifts = [(k//48) % 4 for k in range(n)]
    bypass = [int(240 <= k < 288) for k in range(n)]
    clear  = [int(k == 180) for k in range(n)]

    def model(c):
        ri, rq = np.zeros(n, np.int64), np.zeros(n, np.int64)
        for k in range(n):
            if bypass[k]:
                ri[k], rq[k] = c[0][k], c[1][k]
            else:
                yi, yq = models.gain_model([c[0][k]], [c[1][k]], gain, shifts[k])
                ri[k], rq[k] = yi[0], yq[0]
        return [ri, rq]

    return dut, cols + [shifts, bypass, clear], n - 4, model, False, False, \
        (dut.shift, dut.bypass, dut.clear_sat)

def spec_log2():
    from litedsp.level.logdb import LiteDSPLog2
    n    = 300
    dut  = LiteDSPLog2(in_width=32, frac_bits=8, with_csr=False)
    cols = _rand_cols(1, n, lo=0, hi=2**31 - 1)                    # Unsigned magnitude input.
    return dut, cols, n - 4, lambda c: [models.log2_model(np.array(c[0]))]

def spec_clipper():
    from litedsp.level.clipper import LiteDSPClipper
    n, threshold = 300, 12000                                      # Random +/-20000: clips often.
    dut = LiteDSPClipper(data_width=16, with_csr=False)            # bypass reset = 0 (process).
    dut.threshold.reset = threshold
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: list(models.clipper_model(c[0], c[1], threshold))

def spec_squelch():
    from litedsp.level.squelch import LiteDSPSquelch
    n = 300
    open_thr, close_thr = 400_000_000, 100_000_000                 # ~mean power 2.7e8: gate toggles.
    dut = LiteDSPSquelch(data_width=16, with_csr=False)
    dut.open_threshold.reset  = open_thr
    dut.close_threshold.reset = close_thr
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: list(models.squelch_model(c[0], c[1], open_thr, close_thr))

def spec_agc():
    from litedsp.level.agc import LiteDSPAGC
    n, target, gain_max = 300, 8000, 320
    dut = LiteDSPAGC(data_width=16, with_csr=False, feedback_delay=2, gain_max=gain_max)
    dut.target.reset = target
    cols = _rand_cols(2, n)
    # Silence first drives gain into the upper clamp; a full-scale complex burst then drives it
    # into the lower clamp. The random tail covers normal acquisition and both magnitude arms.
    for c in cols:
        c[:32] = [0]*32
    for k in range(32, 96):
        cols[0][k] =  30000 if (k & 1) else -30000
        cols[1][k] =  20000 if (k & 2) else -20000
    return dut, cols, n - 4, lambda c: list(models.agc_model(
        c[0], c[1], target, gain_max=gain_max, feedback_delay=2))

def spec_envelope():
    from litedsp.level.peak import LiteDSPEnvelopeDetector
    n, attack, release = 300, 2, 6
    dut  = LiteDSPEnvelopeDetector(data_width=16, attack=attack, release=release, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.envelope_detector_model(
        c[0], c[1], attack=attack, release=release)]

# Comm ---------------------------------------------------------------------------------------------

def spec_soft_demapper():
    from litedsp.comm.soft_demap import LiteDSPSoftDemapper
    n, bpa, spacing, scale = 300, 2, 6000, 24                      # 16-QAM, ~full LLR range.
    dut = LiteDSPSoftDemapper(bits_per_axis=bpa, spacing=spacing, llr_bits=4, data_width=16,
        with_csr=False)
    dut.llr_scale.reset = scale
    cols = _rand_cols(2, n, lo=-32768, hi=32767)
    return dut, cols, n - 4, lambda c: [models.soft_demap_model(c[0], c[1], bits_per_axis=bpa,
        spacing=spacing, llr_bits=4, llr_scale=scale)]

def spec_slicer():
    from litedsp.comm.slicer import LiteDSPSlicer
    n, bpa, spacing = 300, 2, 6000                                 # 16-QAM over the full range.
    dut  = LiteDSPSlicer(data_width=16, bits_per_axis=bpa, spacing=spacing, with_csr=False)
    cols = _rand_cols(2, n, lo=-32768, hi=32767)
    return dut, cols, n - 4, lambda c: list(models.slicer_model(c[0], c[1], bits_per_axis=bpa,
        spacing=spacing))

def spec_diff_encoder():
    from litedsp.comm.diff import LiteDSPDifferentialEncoder
    n, M = 300, 4                                                  # DQPSK symbol indices.
    dut  = LiteDSPDifferentialEncoder(modulus=M, with_csr=False)
    cols = _rand_cols(1, n, lo=0, hi=M - 1)
    return dut, cols, n - 4, lambda c: [models.diff_encode_model(c[0], M)]

def spec_diff_decoder():
    from litedsp.comm.diff import LiteDSPDifferentialDecoder
    n, M = 300, 4
    dut  = LiteDSPDifferentialDecoder(modulus=M, with_csr=False)
    cols = _rand_cols(1, n, lo=0, hi=M - 1)
    return dut, cols, n - 4, lambda c: [models.diff_decode_model(c[0], M)]

def _spec_viterbi_decoder(acs_parallelism=None):
    from litedsp.comm.viterbi import LiteDSPViterbiDecoder
    n, prng = 448, random.Random(19)
    dut  = LiteDSPViterbiDecoder(with_csr=False, decision_memory=True,
        normalize_interval=16, acs_parallelism=acs_parallelism)
    data = _conv_symbols([prng.randint(0, 1) for _ in range(n)])
    for pos in range(73, n - 16, 29):
        data[pos] ^= 1 << ((pos // 29) & 1)                      # Exercise alternate survivors.
    return dut, [data], n - dut.traceback - 8, lambda c: [models.viterbi_model(c[0])]

def spec_viterbi_decoder():
    return _spec_viterbi_decoder()

def spec_viterbi_decoder_acs32():
    return _spec_viterbi_decoder(acs_parallelism=32)

def _spec_viterbi_decoder_soft(acs_parallelism=None):
    from litedsp.comm.viterbi import LiteDSPViterbiDecoder
    n, llr_bits, prng = 384, 4, random.Random(20)
    dut = LiteDSPViterbiDecoder(llr_bits=llr_bits, with_csr=False,
        decision_memory=True, normalize_interval=16, acs_parallelism=acs_parallelism)
    syms = _conv_symbols([prng.randint(0, 1) for _ in range(n)])
    llrs = []
    for pos, sym in enumerate(syms):
        values = []
        for bit in range(2):
            magnitude = 2 + ((pos + 3*bit) % 6)
            value = -magnitude if (sym >> bit) & 1 else magnitude
            if pos % 31 == 7 + bit:
                value = 0                                      # Punctured/erased observation.
            elif pos % 37 == 11 + bit:
                value = -value                                 # Controlled soft error.
            values.append(value)
        llrs.append(values)
    words = models.pack_llrs(llrs, llr_bits)
    return dut, [words], n - dut.traceback - 8, \
        lambda c: [models.viterbi_model(c[0], llr_bits=llr_bits)]

def spec_viterbi_decoder_soft():
    return _spec_viterbi_decoder_soft()

def spec_viterbi_decoder_soft_acs32():
    return _spec_viterbi_decoder_soft(acs_parallelism=32)

def spec_puncturer():
    from litedsp.comm.puncture import LiteDSPPuncturer, PUNCTURE_3_4
    n = 180
    dut  = LiteDSPPuncturer(pattern=PUNCTURE_3_4, with_csr=False)
    data = _rand_cols(1, n, lo=0, hi=3, seed=23)[0]
    phase_rst = [int(k == 90) for k in range(n)]
    ref = (models.puncture_model(data[:91], PUNCTURE_3_4) +
           models.puncture_model(data[91:], PUNCTURE_3_4))
    return dut, [data, phase_rst], len(ref), lambda c: [
        models.puncture_model(c[0][:91], PUNCTURE_3_4) +
        models.puncture_model(c[0][91:], PUNCTURE_3_4)], False, False, (dut.phase_rst,)

def spec_depuncturer():
    from litedsp.comm.puncture import LiteDSPDepuncturer, PUNCTURE_3_4
    n, llr_bits = 180, 4
    dut  = LiteDSPDepuncturer(pattern=PUNCTURE_3_4, llr_bits=llr_bits, with_csr=False)
    cols = _rand_cols(1, n, lo=-7, hi=7, seed=29)
    ref  = models.depuncture_model(cols[0], PUNCTURE_3_4, llr_bits=llr_bits)
    return dut, cols, len(ref), lambda c: [models.depuncture_model(
        c[0], PUNCTURE_3_4, llr_bits=llr_bits)]

def _block_permuter_spec(deinterleave=False):
    from litedsp.comm.interleaver import LiteDSPBlockInterleaver, LiteDSPBlockDeinterleaver
    rows, columns, blocks = 3, 5, 3
    n = rows*columns*blocks
    cls   = LiteDSPBlockDeinterleaver if deinterleave else LiteDSPBlockInterleaver
    model = models.block_deinterleave_model if deinterleave else models.block_interleave_model
    dut   = cls(rows=rows, cols=columns, width=8, with_csr=False)
    data  = _rand_cols(1, n, lo=0, hi=255, seed=31 + deinterleave)[0]
    first = [int(k % (rows*columns) == 0) for k in range(n)]
    last  = [int(k % (rows*columns) == rows*columns - 1) for k in range(n)]
    out_first = first
    out_last  = last
    return dut, [data, first, last], n, lambda c: [
        model(c[0], rows=rows, cols=columns), out_first, out_last], True, True

def spec_block_interleaver():
    return _block_permuter_spec(deinterleave=False)

def spec_block_deinterleaver():
    return _block_permuter_spec(deinterleave=True)

def spec_rs_encoder():
    from litedsp.comm.rs import LiteDSPRSEncoder
    n, k = 255, 251
    dut  = LiteDSPRSEncoder(n=n, k=k, with_csr=False)
    data = _rand_cols(1, k, lo=0, hi=255, seed=41)[0]
    first = [1] + [0]*(k - 1)
    last  = [0]*(k - 1) + [1]
    out_first = [1] + [0]*(n - 1)
    out_last  = [0]*(n - 1) + [1]
    return dut, [data, first, last], n, lambda c: [
        models.rs_encode_model(c[0], n=n, k=k), out_first, out_last], True, True

def _spec_rs_decoder(architecture="classic"):
    from litedsp.comm.rs import LiteDSPRSDecoder
    n, k = 255, 251
    msg = _rand_cols(1, k, lo=0, hi=255, seed=43)[0]
    rx  = models.rs_encode_model(msg, n=n, k=k)
    rx[17]  ^= 0x53
    rx[211] ^= 0xa6
    dut   = LiteDSPRSDecoder(n=n, k=k, with_csr=False, architecture=architecture)
    first = [1] + [0]*(n - 1)
    last  = [0]*(n - 1) + [1]
    out_first = [1] + [0]*(k - 1)
    out_last  = [0]*(k - 1) + [1]
    return dut, [rx, first, last], k, lambda c: [
        models.rs_decode_model(c[0], n=n, k=k)[0], out_first, out_last], True, True

def spec_rs_decoder():
    return _spec_rs_decoder()

def spec_rs_decoder_pipelined():
    return _spec_rs_decoder(architecture="pipelined")

def spec_ccsds_rs_encoder():
    from litedsp.comm.rs import LiteDSPCCSDSRSEncoder
    n, k = 255, 223
    dut = LiteDSPCCSDSRSEncoder(with_csr=False)
    data = _rand_cols(1, k, lo=0, hi=255, seed=47)[0]
    first = [1] + [0]*(k - 1)
    last = [0]*(k - 1) + [1]
    out_first = [1] + [0]*(n - 1)
    out_last = [0]*(n - 1) + [1]
    return dut, [data, first, last], n, lambda c: [
        models.ccsds_rs_encode_model(c[0]), out_first, out_last], True, True

def spec_ccsds_rs_decoder():
    from litedsp.comm.rs import LiteDSPCCSDSRSDecoder
    n, k = 255, 223
    messages = [_rand_cols(1, k, lo=0, hi=255, seed=seed)[0]
                for seed in (49, 50, 51, 52)]
    blocks = [models.ccsds_rs_encode_model(message) for message in messages]
    blocks[1][17] ^= 0x53
    blocks[1][211] ^= 0xa6
    rng = np.random.default_rng(72)
    for position in rng.choice(n, 16, replace=False):
        blocks[2][int(position)] ^= int(rng.integers(1, 256))
    rng = np.random.default_rng(73)
    for position in rng.choice(n, 17, replace=False):
        blocks[3][int(position)] ^= int(rng.integers(1, 256))
    expected = [byte for block in blocks for byte in models.ccsds_rs_decode_model(block)[0]]
    received = [byte for block in blocks for byte in block]
    dut = LiteDSPCCSDSRSDecoder(with_csr=False, architecture="pipelined")
    first = [int(i % n == 0) for i in range(4*n)]
    last = [int(i % n == n - 1) for i in range(4*n)]
    clear = [int(i == 3*n) for i in range(4*n)]
    out_first = [int(i % k == 0) for i in range(4*k)]
    out_last = [int(i % k == k - 1) for i in range(4*k)]
    return dut, [received, first, last, clear], 4*k, lambda c: [
        expected, out_first, out_last], True, True, (dut.clear,)

def spec_ldpc_encoder():
    from litedsp.comm.ldpc import LiteDSPLDPCEncoder, LDPC_K, LDPC_N
    dut  = LiteDSPLDPCEncoder(with_csr=False)
    data = _rand_cols(1, LDPC_K, lo=0, hi=1, seed=53)[0]
    first = [1] + [0]*(LDPC_K - 1)
    last  = [0]*(LDPC_K - 1) + [1]
    out_first = [1] + [0]*(LDPC_N - 1)
    out_last  = [0]*(LDPC_N - 1) + [1]
    return dut, [data, first, last], LDPC_N, lambda c: [
        models.ldpc_encode_model(c[0]), out_first, out_last], True, True

def _spec_ldpc_decoder(z_parallel=False):
    from litedsp.comm.ldpc import LiteDSPLDPCDecoder, LDPC_K, LDPC_N
    from litedsp.comm.ldpc_parallel import LiteDSPLDPCDecoderZParallel
    def random_message(seed):
        return [int(b) for b in np.random.default_rng(seed).integers(0, 2, LDPC_K)]

    def awgn_llrs(message, ebno_db, seed):
        codeword = models.ldpc_encode_model(message)
        rng   = np.random.default_rng(seed)
        sigma = np.sqrt(1/(2*0.5*10**(ebno_db/10)))
        y     = (1 - 2*np.asarray(codeword, dtype=np.float64)) + rng.normal(0, sigma, LDPC_N)
        return [int(v) for v in np.clip(np.round(4*y), -7, 7)]

    clean = random_message(59)
    blocks = [
        [7*(1 - 2*b) for b in models.ldpc_encode_model(clean)],
        awgn_llrs(random_message(54), 2.5, 64),
        awgn_llrs(random_message(52), 2.0, 62),
        [int(v) for v in np.random.default_rng(50).integers(-7, 8, LDPC_N)],
    ]
    expected = [bit for block in blocks for bit in models.ldpc_decode_model(block)[0]]
    llrs = [v for block in blocks for v in block]
    cls = LiteDSPLDPCDecoderZParallel if z_parallel else LiteDSPLDPCDecoder
    dut = cls(llr_bits=4, max_iters=8, with_csr=False)
    first = [int(k % LDPC_N == 0) for k in range(len(llrs))]
    last  = [int(k % LDPC_N == LDPC_N - 1) for k in range(len(llrs))]
    clear = [int(k == 3*LDPC_N) for k in range(len(llrs))]
    n_out = len(blocks)*LDPC_K
    out_first = [int(k % LDPC_K == 0) for k in range(n_out)]
    out_last  = [int(k % LDPC_K == LDPC_K - 1) for k in range(n_out)]
    return dut, [llrs, first, last, clear], n_out, lambda c: [
        expected, out_first, out_last], True, True, (dut.clear,)

def spec_ldpc_decoder():
    return _spec_ldpc_decoder()

def spec_ldpc_decoder_z_parallel():
    return _spec_ldpc_decoder(z_parallel=True)

def spec_cp_insert():
    from litedsp.comm.ofdm import LiteDSPCPInsert
    N, CP, n_frames = 16, 4, 4
    n = N*n_frames
    dut = LiteDSPCPInsert(fft_size=N, cp_len=CP, data_width=16, with_csr=False)
    i, q = _rand_cols(2, n, lo=-12000, hi=12000, seed=74)
    first = [int(k % N == 0) for k in range(n)]
    last  = [int(k % N == N - 1) for k in range(n)]
    out_n = (N + CP)*n_frames
    out_first = [int(k % (N + CP) == 0) for k in range(out_n)]
    out_last  = [int(k % (N + CP) == N + CP - 1) for k in range(out_n)]
    return dut, [i, q, first, last], out_n, lambda c: [
        *models.cp_insert_model(c[0], c[1], fft_size=N, cp_len=CP), out_first, out_last], \
        True, True

def spec_cp_remove():
    from litedsp.comm.ofdm import LiteDSPCPRemove
    N, CP, n_frames = 16, 4, 4
    payload_i, payload_q = _rand_cols(2, N*n_frames, lo=-12000, hi=12000, seed=75)
    i, q = models.cp_insert_model(payload_i, payload_q, fft_size=N, cp_len=CP)
    i, q = i.tolist(), q.tolist()
    n = len(i)
    dut = LiteDSPCPRemove(fft_size=N, cp_len=CP, data_width=16, with_csr=False)
    first = [int(k % (N + CP) == 0) for k in range(n)]
    last  = [int(k % (N + CP) == N + CP - 1) for k in range(n)]
    out_n = N*n_frames
    out_first = [int(k % N == 0) for k in range(out_n)]
    out_last  = [int(k % N == N - 1) for k in range(out_n)]
    return dut, [i, q, first, last], out_n, lambda c: [
        *models.cp_remove_model(c[0], c[1], fft_size=N, cp_len=CP), out_first, out_last], \
        True, True

def spec_correlator():
    from litedsp.comm.correlator import LiteDSPCorrelator
    n, seq = 340, [1, 1, 1, -1, -1, 1, -1]                         # Barker-7 matched filter.
    dut    = LiteDSPCorrelator(sequence=seq, data_width=16, with_csr=False)
    scale  = (1 << 15) - 1                                         # Taps: reversed, full-scale.
    coeffs = [c*scale for c in reversed(seq)]
    cols   = _rand_cols(2, n, lo=-8000, hi=8000)
    for c in cols:
        c[240:] = [0]*(n - 240)
    reset  = [int(k == 260) for k in range(n)]
    bypass = [int(k >= 280) for k in range(n)]
    return dut, cols + [reset, bypass], n - 8, \
        lambda c: list(models.fir_complex_model(c[0], c[1], coeffs)), \
        False, False, (dut.fir.reset, dut.fir.bypass)

def _spec_frame_sync(architecture="classic"):
    from litedsp.comm.frame_sync import LiteDSPFrameSync
    sequence, n, frame_len = [1, 1, 1, -1, -1, 1, -1], 256, 16
    rng = np.random.RandomState(3)
    xi  = rng.randint(-1500, 1500, n).astype(np.int64)
    xq  = rng.randint(-1500, 1500, n).astype(np.int64)
    for pos in (40, 120):
        xi[pos:pos + len(sequence)] = [4000*c for c in sequence]
        xq[pos:pos + len(sequence)] = 0
    threshold = int(0.8*(1 << 14))
    dut = LiteDSPFrameSync(sequence, data_width=16, frame_len=frame_len,
        peak_window=4, with_csr=False, architecture=architecture)
    dut.threshold.reset = threshold
    dut.offset.reset = 3
    fir_reset = [int(k == 196) for k in range(n)]
    clear  = [int(k == 180) for k in range(n)]
    cols  = [xi, xq, fir_reset, clear]
    n_out = n - dut.latency - 4
    return dut, cols, n_out, lambda c: list(models.frame_sync_model(
        c[0], c[1], sequence, threshold, frame_len=frame_len, offset=3)[:4]), \
        False, True, (dut.fir_r.reset, dut.clear_count)

def spec_frame_sync():
    return _spec_frame_sync()

def spec_frame_sync_pipelined():
    return _spec_frame_sync(architecture="pipelined")

# Correction ---------------------------------------------------------------------------------------

def spec_dc_offset():
    from litedsp.correction.dc_offset import LiteDSPDCOffset
    n, mu = 300, 10
    dut  = LiteDSPDCOffset(data_width=16, mu=mu, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.dc_offset_model(c[0], mu),
                                        models.dc_offset_model(c[1], mu)]

# Analysis -----------------------------------------------------------------------------------------

def spec_magnitude():
    from litedsp.analysis.magnitude import LiteDSPMagnitude
    n    = 300
    dut  = LiteDSPMagnitude(data_width=16, with_csr=False)
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: [models.magnitude_model(np.array(c[0]), np.array(c[1]))]

def spec_window():
    # Capture the internally generated frame markers as well as the windowed payload. Together
    # with the framed codec/OFDM specs this keeps both tag directions exercised in the generic TB.
    from litedsp.analysis.window import LiteDSPWindow, window_coefficients
    n, n_win = 192, 64
    dut    = LiteDSPWindow(n=n_win, data_width=16, window="hann", with_csr=False)
    coeffs = window_coefficients(n_win, "hann")
    cols   = _rand_cols(2, n)
    first  = [int(k % n_win == 0) for k in range(n)]
    last   = [int(k % n_win == n_win - 1) for k in range(n)]
    return dut, cols, n - 4, lambda c: [
        *models.window_model(c[0], c[1], coeffs), first, last], False, True

def spec_psd():
    # Framed *output* (first/last markers on the emitted spectrum) is fine for the generic TB:
    # it captures the payload samples in order and ignores the markers. data_width=14 keeps
    # power_width = 2*14 + avg_log2 <= 32 (the TB reads outputs as int32); a short explicit
    # fft_latency exercises the upstream-FFT fill skip while the stimulus is fed directly.
    from litedsp.analysis.psd import LiteDSPPSD
    n, N, avg_log2 = 300, 16, 2                                    # 4 spectra of N bins.
    dut  = LiteDSPPSD(N=N, fft_latency=2, data_width=14, avg_log2=avg_log2, with_csr=False)
    # Constant non-zero power is invariant under linear, exponential, max and min combining.
    # It therefore exercises every runtime mode, clear, FFT-fill skip and readout arm in one
    # deterministic co-simulation while test_psd.py remains the detailed per-mode value check.
    ci, cq = 1234, -567
    cols   = [[ci]*n, [cq]*n]
    # The pending sample supplies controls while READ backpressures the sink, so retain each
    # mode through that boundary sample (skip consumes indices 0..1; spectra end at 65, 129,
    # 193 and 257). The first sample after each boundary may use the preceding mode, which is
    # harmless for constant power and still exercises all four combine/readout selections.
    mode   = [0 if k <= 66 else 1 if k <= 130 else 2 if k <= 194 else 3 for k in range(n)]
    clear  = [int(k in (100, 220)) for k in range(n)]
    power  = ci*ci + cq*cq
    return dut, cols + [mode, clear], 4*N, lambda c: [[power]*(4*N)], \
        False, False, (dut.mode, dut.clear)

def _spec_parallel_fft(n_samples=2, implementation="split", core_architecture="classic",
    feedback_pipeline=False, complex_multiplier="four"):
    from litedsp.analysis.fft_parallel import LiteDSPParallelFFT
    N, n_frames = 16, 4
    rng = np.random.RandomState(73 + n_samples)
    xi  = rng.randint(-25000, 25000, n_frames*N)
    xq  = rng.randint(-25000, 25000, n_frames*N)

    def pack(values):
        width = 16*n_samples
        word  = sum((int(v) & 0xffff) << (16*k) for k, v in enumerate(values))
        return word - (1 << width) if word >= (1 << (width - 1)) else word

    in_i = [pack(xi[k:k + n_samples]) for k in range(0, len(xi), n_samples)]
    in_q = [pack(xq[k:k + n_samples]) for k in range(0, len(xq), n_samples)]
    beats = N//n_samples
    first = [int(k % beats == 0) for k in range(len(in_i))]
    last  = [int(k % beats == beats - 1) for k in range(len(in_i))]
    ref_i, ref_q = [], []
    for f in range(n_frames - 1):
        yi, yq = models.fft_fixed_model(xi[f*N:(f + 1)*N], xq[f*N:(f + 1)*N])
        ref_i += [pack(yi[k:k + n_samples]) for k in range(0, N, n_samples)]
        ref_q += [pack(yq[k:k + n_samples]) for k in range(0, N, n_samples)]
    n_out = (n_frames - 1)*beats
    out_first = [int(k % beats == 0) for k in range(n_out)]
    out_last  = [int(k % beats == beats - 1) for k in range(n_out)]
    dut = LiteDSPParallelFFT(N=N, n_samples=n_samples, implementation=implementation,
        core_architecture=core_architecture, feedback_pipeline=feedback_pipeline,
        complex_multiplier=complex_multiplier, with_csr=False)
    return dut, [in_i, in_q, first, last], n_out, \
        lambda c: [ref_i, ref_q, out_first, out_last], True, True

def spec_parallel_fft():
    return _spec_parallel_fft()

def spec_parallel_fft_folded():
    return _spec_parallel_fft(core_architecture="folded")

def spec_parallel_fft_native_x2():
    return _spec_parallel_fft(2, implementation="native", feedback_pipeline=True)

def spec_parallel_fft_native_x4():
    return _spec_parallel_fft(4, implementation="native", feedback_pipeline=True)

def spec_parallel_fft_native_x4_dsp():
    return _spec_parallel_fft(4, implementation="native", feedback_pipeline=True,
        complex_multiplier="three")

def spec_welch():
    from litedsp.analysis.welch import LiteDSPWelchPSD
    n, N, avg_log2 = 300, 16, 2                                    # 4 spectra of N bins.
    dut  = LiteDSPWelchPSD(N=N, data_width=14, avg_log2=avg_log2, window="hann", with_csr=False)
    cols = _rand_cols(2, n, lo=-8000, hi=8000)                     # 14-bit signed range.
    return dut, cols, 4*N, lambda c: [np.concatenate(
        models.welch_model(c[0], c[1], N, avg_log2=avg_log2, window="hann", data_width=14))]

# Stream -------------------------------------------------------------------------------------------

def spec_conjugate():
    from litedsp.stream.ops import LiteDSPConjugate
    n    = 300
    dut  = LiteDSPConjugate(data_width=16)                         # Pure comb map: no CSRs.
    cols = _rand_cols(2, n, lo=-32768, hi=32767)
    return dut, cols, n - 2, lambda c: list(models.conjugate_model(c[0], c[1]))

def spec_swap_iq():
    from litedsp.stream.ops import LiteDSPSwapIQ
    n    = 300
    dut  = LiteDSPSwapIQ(data_width=16)
    cols = _rand_cols(2, n, lo=-32768, hi=32767)
    return dut, cols, n - 2, lambda c: list(models.swap_iq_model(c[0], c[1]))

def spec_negate():
    from litedsp.stream.ops import LiteDSPNegate
    n    = 300
    dut  = LiteDSPNegate(data_width=16)
    cols = _rand_cols(2, n, lo=-32768, hi=32767)                   # -full-scale wraps (no saturation).
    return dut, cols, n - 2, lambda c: list(models.negate_model(c[0], c[1]))

def spec_combine():
    from litedsp.stream.combine import LiteDSPCombine
    n    = 300
    dut  = LiteDSPCombine(n_channels=2, data_width=16, with_csr=False)  # enable reset = all-ones.
    cols = _rand_cols(4, n)                                        # sinks[0](i,q), sinks[1](i,q).
    return dut, cols, n - 4, lambda c: list(models.combine_model([c[0], c[2]], [c[1], c[3]]))

# Motor Control ------------------------------------------------------------------------------------

def spec_clarke():
    from litedsp.motor.transforms import LiteDSPClarke
    n    = 300
    dut  = LiteDSPClarke(data_width=16, with_csr=False)
    cols = _rand_cols(3, n, lo=-30000, hi=30000)                      # sink(a, b, c).
    return dut, cols, n - 4, lambda c: list(models.clarke_model(c[0], c[1], c[2]))

def spec_clarke_three_wire():
    from litedsp.motor.transforms import LiteDSPClarke
    n    = 300
    dut  = LiteDSPClarke(data_width=16, three_wire=True, with_csr=False)
    cols = _rand_cols(3, n, lo=-30000, hi=30000)
    return dut, cols, n - 4, lambda c: list(models.clarke_model(c[0], c[1], c[2], three_wire=True))

def spec_inverse_clarke():
    from litedsp.motor.transforms import LiteDSPInverseClarke
    n    = 300
    dut  = LiteDSPInverseClarke(data_width=16, with_csr=False)
    cols = _rand_cols(2, n, lo=-30000, hi=30000)                      # sink(i, q).
    return dut, cols, n - 4, lambda c: list(models.inverse_clarke_model(c[0], c[1]))

def _spec_sincos(method):
    from litedsp.motor.transforms import LiteDSPSinCos
    n    = 300
    dut  = LiteDSPSinCos(data_width=16, angle_width=16, method=method, with_csr=False)
    cols = _rand_cols(1, n, lo=-32768, hi=32767)                      # sink(angle).
    return dut, cols, n - 4, lambda c: list(models.sincos_model(c[0], method=method))

def spec_sincos():
    return _spec_sincos("rom")

def spec_sincos_cordic():
    return _spec_sincos("cordic")

def spec_angle_ramp():
    from litedsp.motor.transforms import LiteDSPAngleRamp
    n, phase_inc = 256, 0x0123_4567
    dut = LiteDSPAngleRamp(angle_width=16, phase_bits=32, with_csr=False)
    dut.phase_inc.reset = phase_inc
    return dut, [], n, lambda c: [models.angle_ramp_model(phase_inc, n)]

def _spec_park(cls, model):
    n    = 300
    dut  = cls(data_width=16, angle_width=16, with_csr=False)
    cols = _rand_cols(2, n, lo=-30000, hi=30000) + _rand_cols(1, n, lo=-32768, hi=32767, seed=2)
    return dut, cols, n - 4, lambda c: list(model(c[0], c[1], c[2]))   # sink(i,q), sink_angle.

def spec_park():
    from litedsp.motor.transforms import LiteDSPPark
    return _spec_park(LiteDSPPark, models.park_model)

def spec_inverse_park():
    from litedsp.motor.transforms import LiteDSPInversePark
    return _spec_park(LiteDSPInversePark, models.inverse_park_model)

def spec_pi_controller():
    from litedsp.motor.pi import LiteDSPPIController
    n    = 300
    dut  = LiteDSPPIController(data_width=16, with_csr=False)
    cols = _rand_cols(1, n, lo=-30000, hi=30000)                      # sink(data).
    # Per-sample controls: a setpoint step, gains and a limit low enough to clamp, then a
    # short open-loop window (clamped feedforward = 0 with the integrator held).
    setpoint  = [4000 if k < 150 else -9000 for k in range(n)]
    kp        = [int(1.5*4096)]*n
    ki        = [int(0.2*4096)]*n
    limit     = [12000]*n
    open_loop = [int(200 <= k < 230) for k in range(n)]
    ctrl = [setpoint, kp, ki, limit, open_loop]
    return dut, cols + ctrl, n - 4, \
        lambda c: [models.pi_controller_model(c[0], np.array(c[1]), np.array(c[2]),
            np.array(c[3]), np.array(c[4]), open_loop=np.array(c[5]))], \
        False, False, (dut.setpoint, dut.kp, dut.ki, dut.limit, dut.open_loop)

def spec_pi_controller_ref():
    from litedsp.motor.pi import LiteDSPPIController
    n    = 300
    dut  = LiteDSPPIController(data_width=16, setpoint_stream=True, anti_windup="clamp",
        with_csr=False)
    dut.kp.reset, dut.ki.reset, dut.limit.reset = int(0.7*4096), int(0.05*4096), 20000
    cols = _rand_cols(2, n, lo=-30000, hi=30000)                      # sink(data), sink_ref(data).
    return dut, cols, n - 4, lambda c: [models.pi_controller_model(c[0], np.array(c[1]),
        int(0.7*4096), int(0.05*4096), 20000, anti_windup="clamp")]

def _spec_dq_controller(decoupling):
    from litedsp.motor.pi import LiteDSPDQController
    n     = 300
    dut   = LiteDSPDQController(data_width=16, decoupling=decoupling, with_csr=False)
    gains = dict(kp_d=int(0.8*4096), ki_d=int(0.1*4096), kp_q=int(1.2*4096), ki_q=int(0.15*4096))
    dut.setpoint_d.reset, dut.setpoint_q.reset, dut.limit.reset = -2000, 9000, 20000
    for k, v in gains.items():
        getattr(dut, k).reset = v
    dut.speed.reset, dut.l_pu.reset, dut.psi_pu.reset = 12000, 5000, 20000
    cols = _rand_cols(2, n, lo=-30000, hi=30000)                      # sink(i, q).
    return dut, cols, n - 4, lambda c: list(models.dq_controller_model(c[0], c[1], -2000, 9000,
        limit=20000, decoupling=decoupling, speed=12000, l_pu=5000, psi_pu=20000, **gains))

def spec_dq_controller():
    return _spec_dq_controller(False)

def spec_dq_controller_decoupling():
    return _spec_dq_controller(True)

def spec_slew_limiter():
    from litedsp.motor.limiter import LiteDSPSlewLimiter
    n    = 300
    dut  = LiteDSPSlewLimiter(data_width=16, with_csr=False)
    cols = _rand_cols(1, n, lo=-30000, hi=30000)
    rate = [500 if k < 150 else 6000 for k in range(n)]
    return dut, cols + [rate], n - 4, \
        lambda c: [models.slew_limiter_model(c[0], np.array(c[1]))], False, False, (dut.rate,)

def spec_svpwm():
    from litedsp.motor.svpwm import LiteDSPSVPWM
    n    = 300
    dut  = LiteDSPSVPWM(data_width=16, with_csr=False)
    cols = _rand_cols(2, n, lo=-32000, hi=32000)                      # sink(i, q).
    injection = [int(not (100 <= k < 200)) for k in range(n)]
    return dut, cols + [injection], n - 4, \
        lambda c: list(models.svpwm_model(c[0], c[1], np.array(c[2]))), False, False, \
        (dut.injection,)

def spec_bitstream_decimator():
    from litedsp.filter.bitstream import LiteDSPBitstreamDecimator
    R, n_out = 64, 40
    dut  = LiteDSPBitstreamDecimator(data_width=24, decimation=R, n_stages=4, with_csr=False)
    cols = _rand_cols(1, R*n_out, lo=0, hi=1)                          # sink(data): bits.
    return dut, cols, n_out - 4, lambda c: [models.bitstream_decimator_model(c[0], R, 4,
        data_width=24)]

def spec_sigma_delta_filter():
    from litedsp.motor.sense import LiteDSPSigmaDeltaFilter
    R, n_out = 64, 40
    dut  = LiteDSPSigmaDeltaFilter(data_width=16, n_channels=3, decimation=R, n_stages=3,
        r_max=256, with_csr=False)
    cols = _rand_cols(3, R*n_out, lo=0, hi=1)                          # sinks[0..2](data).
    return dut, cols, n_out - 4, lambda c: list(models.sigma_delta_filter_model(
        [c[0], c[1], c[2]], R, 32767, r_max=256)[0])

def spec_overcurrent_trip():
    from litedsp.motor.sense import LiteDSPOvercurrentTrip
    n    = 300
    dut  = LiteDSPOvercurrentTrip(data_width=16, with_csr=False)
    cols = _rand_cols(3, n, lo=-30000, hi=30000)                       # sink(a, b, c).
    return dut, cols, n - 4, lambda c: list(models.overcurrent_trip_model(c[0], c[1], c[2],
        20000)[:3])

def spec_angle_tracker():
    from litedsp.motor.observer import LiteDSPAngleTracker
    n    = 300
    dut  = LiteDSPAngleTracker(angle_width=16, with_csr=False)
    cols = _rand_cols(1, n, lo=-32768, hi=32767)                      # sink(angle).
    kp   = [4 if k < 150 else 3 for k in range(n)]
    ki   = [10 if k < 150 else 8 for k in range(n)]
    return dut, cols + [kp, ki], n - 4, \
        lambda c: [models.angle_tracker_model(c[0], np.array(c[1]), np.array(c[2]))[0]], \
        False, False, (dut.kp_shift, dut.ki_shift)

def spec_smo_observer():
    from litedsp.motor.observer import LiteDSPSMObserver
    n     = 300
    gains = dict(g_v=1365, g_r=68, k_sm=9830, lpf_shift=3)
    dut   = LiteDSPSMObserver(data_width=16, angle_width=16, with_csr=False)
    for k, v in gains.items():
        getattr(dut, k).reset = v
    cols = _rand_cols(4, n, lo=-20000, hi=20000)                      # sink_i(i,q), sink_v(i,q).
    return dut, cols, n - 4, lambda c: [models.smo_model(c[0], c[1], c[2], c[3], **gains)]

def spec_foc():
    from litedsp.motor.foc import LiteDSPFOC
    n     = 300
    gains = dict(kp_d=int(0.8*4096), ki_d=int(0.1*4096), kp_q=int(1.2*4096), ki_q=int(0.15*4096))
    dut   = LiteDSPFOC(data_width=16, angle_width=16, with_csr=False)
    dut.dq.setpoint_d.reset, dut.dq.setpoint_q.reset, dut.dq.limit.reset = 0, 8000, 20000
    for k, v in gains.items():
        getattr(dut.dq, k).reset = v
    cols = _rand_cols(3, n, lo=-20000, hi=20000) + _rand_cols(1, n, lo=-32768, hi=32767, seed=2)
    return dut, cols, n - 4, lambda c: list(models.foc_model(c[0], c[1], c[2], c[3], 0, 8000,
        limit=20000, **gains))                                        # sink(a,b,c), sink_angle.

# Audio --------------------------------------------------------------------------------------------

def _tdm_cols(n_frames, n_channels, seed=1, lo=-(1 << 23) + 1, hi=(1 << 23) - 1):
    """TDM stimulus columns: (data, channel) for n_frames*n_channels beats."""
    prng = random.Random(seed)
    data, ch = [], []
    for _ in range(n_frames):
        for c in range(n_channels):
            data.append(prng.randint(lo, hi)); ch.append(c)
    return [data, ch]

def spec_volume():
    from litedsp.audio.level import LiteDSPVolume
    n    = 150
    dut  = LiteDSPVolume(data_width=24, n_channels=2, with_csr=False)
    dut.gains[0].reset, dut.gains[1].reset = int(0.5*(1 << 19)), int(2.0*(1 << 19))
    cols = _tdm_cols(n, 2)
    mute = [0 if k < 200 else 0b10 for k in range(2*n)]
    return dut, cols + [mute], 2*n - 4, \
        lambda c: [models.volume_model(c[0], c[1], [int(0.5*(1 << 19)), int(2.0*(1 << 19))],
            np.array(c[2])), np.array(c[1])], False, False, (dut.mute,)

def spec_stereo_matrix():
    from litedsp.audio.level import LiteDSPStereoMatrix
    n    = 150
    dut  = LiteDSPStereoMatrix(data_width=24, with_csr=False)
    coeffs = (20000, -12000, 7000, 30000)
    for name, v in zip("abcd", coeffs):
        getattr(dut, name).reset = v
    cols = _tdm_cols(n, 2)
    def model(c):
        l, r = np.array(c[0][0::2]), np.array(c[0][1::2])
        ol, orr = models.stereo_matrix_model(l, r, *coeffs)
        out = np.empty(2*n, np.int64); out[0::2], out[1::2] = ol, orr
        return [out, np.array(c[1])]
    return dut, cols, 2*n - 4, model

def _spec_dither(shaping):
    from litedsp.audio.dither import LiteDSPDither
    n    = 150
    dut  = LiteDSPDither(data_width=24, out_width=16, n_channels=2, shaping=shaping, with_csr=False)
    cols = _tdm_cols(n, 2)
    s_en = [int(not (100 <= k < 200)) for k in range(2*n)]
    return dut, cols + [s_en], 2*n - 4, \
        lambda c: [models.dither_model(c[0], c[1], shaping=shaping, shaping_enable=np.array(c[2])),
                   np.array(c[1])], False, False, (dut.shaping_enable,)

def spec_dither():
    return _spec_dither("none")

def spec_dither_ef2():
    return _spec_dither("ef2")

def spec_audio_eq():
    from litedsp.audio.eq      import LiteDSPAudioEQ
    from litedsp.audio.design  import rbj_biquad
    from litedsp.filter.design import biquad_sos_quantize
    n    = 120
    rows = [rbj_biquad("lowshelf", 80, 6.0, sample_rate=48000),
            rbj_biquad("peaking", 1000, -4.0, 1.5, sample_rate=48000),
            rbj_biquad("highshelf", 8000, 3.0, sample_rate=48000)]
    secs = biquad_sos_quantize(rows, 32, 28)[0]
    dut  = LiteDSPAudioEQ(data_width=24, n_bands=3, n_channels=2, sections=secs, with_csr=False)
    cols = _tdm_cols(n, 2, lo=-(1 << 22), hi=(1 << 22))
    mask = [0b111 if k < 160 else 0b101 for k in range(2*n)]
    return dut, cols + [mask], 2*n - 4, \
        lambda c: [models.audio_eq_model(c[0], c[1], secs, band_enable=np.array(c[2])),
                   np.array(c[1])], False, False, (dut.band_enable,)

def spec_log2_lut():
    from litedsp.level.logdb import LiteDSPLog2
    n    = 300
    dut  = LiteDSPLog2(in_width=32, frac_bits=8, lut=True, with_csr=False)
    cols = _rand_cols(1, n, lo=0, hi=(1 << 31) - 1)
    return dut, cols, n - 4, lambda c: [models.log2_model(c[0], 32, 8, lut=True)]

def spec_exp2():
    from litedsp.level.logdb import LiteDSPExp2
    n    = 300
    dut  = LiteDSPExp2(with_csr=False)
    cols = _rand_cols(1, n, lo=-47*256, hi=47*256)
    return dut, cols, n - 4, lambda c: [models.exp2_model(c[0])]

def _spec_compressor(preset, lookahead=0, **ctrl):
    from litedsp.audio.dynamics import LiteDSPCompressor, PRESET_VALUES
    n    = 120
    dut  = LiteDSPCompressor(data_width=24, n_channels=2, lookahead=lookahead, preset=preset,
        with_csr=False)
    for k, v in ctrl.items():
        getattr(dut, k).reset = v
    thr, sa, sb, att, rel, grm = PRESET_VALUES[preset]
    prng = random.Random(3)
    data, chn = [], []
    for k in range(n):
        level = [0.01, 0.1, 0.5, 1.0][(k//30) % 4]
        for c in range(2):
            data.append(int(prng.randint(-(1 << 23) + 1, (1 << 23) - 1)*level)); chn.append(c)
    return dut, [data, chn], 2*n - 4, lambda c: [models.compressor_model(c[0], c[1], thr, sa, sb,
        att, rel, grm, lookahead=lookahead, **ctrl)[0], np.array(c[1])]

def spec_compressor():
    return _spec_compressor("compressor")

def spec_compressor_limiter():
    return _spec_compressor("limiter", lookahead=8)

def spec_compressor_gate():
    return _spec_compressor("gate", detector=1, stereo_link=1, rms_shift=4)

def spec_lfo():
    from litedsp.audio.effects import LiteDSPLFO
    n, inc = 256, 0x0345_6789
    dut = LiteDSPLFO(with_csr=False)
    dut.phase_inc.reset, dut.shape.reset, dut.amplitude.reset = inc, 1, 20000
    return dut, [], n, lambda c: [models.lfo_model(inc, n, 1, 20000)]

def spec_delay_line():
    from litedsp.audio.effects import LiteDSPDelayLine
    n    = 100
    dut  = LiteDSPDelayLine(data_width=24, n_channels=2, max_delay=64, with_csr=False)
    dut.delay.reset, dut.feedback.reset, dut.damping.reset = 9, 19660, 8000
    dut.wet.reset, dut.dry.reset = 22937, 13107
    cols = _tdm_cols(n, 2, lo=-(1 << 22), hi=(1 << 22))
    return dut, cols, 2*n - 4, lambda c: [models.delay_line_model(c[0], c[1], 9, feedback=19660,
        damping=8000, wet=22937, dry=13107, max_delay=64), np.array(c[1])]

# Table --------------------------------------------------------------------------------------------

SPECS = {
    "nco":              spec_nco,
    "cordic_rot":       spec_cordic_rot,
    "mixer":            spec_mixer,
    "carrier_loop":     spec_carrier_loop,
    "carrier_loop_bpsk": spec_carrier_loop_bpsk,
    "carrier_loop_qpsk": spec_carrier_loop_qpsk,
    "carrier_loop_qpsk_pipelined": spec_carrier_loop_qpsk_pipelined,
    "timing_recovery": spec_timing_recovery,
    "timing_recovery_pipelined": spec_timing_recovery_pipelined,
    "timing_recovery_gardner": spec_timing_recovery_gardner,
    "timing_recovery_gardner_pipelined": spec_timing_recovery_gardner_pipelined,
    "fir_real":         spec_fir_real,
    "fir_complex":      spec_fir_complex,
    "fir_complex_pipelined": spec_fir_complex_pipelined,
    "fir_decimator":    spec_fir_decimator,
    "fir_decimator_pipelined": spec_fir_decimator_pipelined,
    "fir_interpolator": spec_fir_interpolator,
    "fir_interpolator_pipelined": spec_fir_interpolator_pipelined,
    "cic_decimator":    spec_cic_decimator,
    "cic_interpolator": spec_cic_interpolator,
    "iir_biquad":       spec_iir_biquad,
    "dc_blocker":       spec_dc_blocker,
    "moving_average":   spec_moving_average,
    "equalizer":        spec_equalizer,
    "pfb_channelizer":  spec_pfb_channelizer,
    "pfb_channelizer_fft": spec_pfb_channelizer_fft,
    "pfb_channelizer_2x": spec_pfb_channelizer_2x,
    "pfb_channelizer_fft_2x": spec_pfb_channelizer_fft_2x,
    "downsampler":      spec_downsampler,
    "upsampler":        spec_upsampler,
    "gain":             spec_gain,
    "log2":             spec_log2,
    "clipper":          spec_clipper,
    "squelch":          spec_squelch,
    "agc":              spec_agc,
    "envelope":         spec_envelope,
    "soft_demapper":    spec_soft_demapper,
    "slicer":           spec_slicer,
    "diff_encoder":     spec_diff_encoder,
    "diff_decoder":     spec_diff_decoder,
    "viterbi_decoder":      spec_viterbi_decoder,
    "viterbi_decoder_soft": spec_viterbi_decoder_soft,
    "viterbi_decoder_acs32": spec_viterbi_decoder_acs32,
    "viterbi_decoder_soft_acs32": spec_viterbi_decoder_soft_acs32,
    "puncturer":        spec_puncturer,
    "depuncturer":      spec_depuncturer,
    "block_interleaver": spec_block_interleaver,
    "block_deinterleaver": spec_block_deinterleaver,
    "rs_encoder":        spec_rs_encoder,
    "rs_decoder":        spec_rs_decoder,
    "rs_decoder_pipelined": spec_rs_decoder_pipelined,
    "ccsds_rs_encoder": spec_ccsds_rs_encoder,
    "ccsds_rs_decoder": spec_ccsds_rs_decoder,
    "ldpc_encoder":      spec_ldpc_encoder,
    "ldpc_decoder":      spec_ldpc_decoder,
    "ldpc_decoder_z_parallel": spec_ldpc_decoder_z_parallel,
    "cp_insert":          spec_cp_insert,
    "cp_remove":          spec_cp_remove,
    "correlator":       spec_correlator,
    "frame_sync":       spec_frame_sync,
    "frame_sync_pipelined": spec_frame_sync_pipelined,
    "dc_offset":        spec_dc_offset,
    "magnitude":        spec_magnitude,
    "window":           spec_window,
    "psd":              spec_psd,
    "parallel_fft":     spec_parallel_fft,
    "parallel_fft_folded":    spec_parallel_fft_folded,
    "parallel_fft_native_x2": spec_parallel_fft_native_x2,
    "parallel_fft_native_x4": spec_parallel_fft_native_x4,
    "parallel_fft_native_x4_dsp": spec_parallel_fft_native_x4_dsp,
    "welch":            spec_welch,
    "conjugate":        spec_conjugate,
    "swap_iq":          spec_swap_iq,
    "negate":           spec_negate,
    "combine":          spec_combine,
    "clarke":           spec_clarke,
    "clarke_three_wire": spec_clarke_three_wire,
    "inverse_clarke":   spec_inverse_clarke,
    "sincos":           spec_sincos,
    "sincos_cordic":    spec_sincos_cordic,
    "angle_ramp":       spec_angle_ramp,
    "park":             spec_park,
    "inverse_park":     spec_inverse_park,
    "pi_controller":    spec_pi_controller,
    "pi_controller_ref": spec_pi_controller_ref,
    "dq_controller":    spec_dq_controller,
    "dq_controller_decoupling": spec_dq_controller_decoupling,
    "slew_limiter":     spec_slew_limiter,
    "svpwm":            spec_svpwm,
    "bitstream_decimator": spec_bitstream_decimator,
    "sigma_delta_filter": spec_sigma_delta_filter,
    "overcurrent_trip": spec_overcurrent_trip,
    "angle_tracker":    spec_angle_tracker,
    "smo_observer":     spec_smo_observer,
    "foc":              spec_foc,
    "volume":           spec_volume,
    "stereo_matrix":    spec_stereo_matrix,
    "dither":           spec_dither,
    "dither_ef2":       spec_dither_ef2,
    "audio_eq":         spec_audio_eq,
    "log2_lut":         spec_log2_lut,
    "exp2":             spec_exp2,
    "compressor":       spec_compressor,
    "compressor_limiter": spec_compressor_limiter,
    "compressor_gate":  spec_compressor_gate,
    "lfo":              spec_lfo,
    "delay_line":       spec_delay_line,
}

# Known failures -----------------------------------------------------------------------------------
#
# Real RTL divergence *found by this co-simulation* goes here, kept visible as XFAIL rather
# than papered over (the golden models and the migen simulation are correct; the emitted
# Verilog is not). Historical catches, all since fixed at the source: Migen prints products
# inline and Verilog sizes ``*`` to its assignment/comparison context, silently truncating
# what migen semantics — and hence the migen-sim-based unit tests — evaluate full-width.
# This hit gain, window and the fft stage twiddle path (the welch chain); all now route the
# product through an explicitly sized full-width Signal before ``scaled()``. Blocks that
# always registered the product first (fir, mixer, iir_biquad) were immune.
KNOWN_FAIL = {}

# Coverage ratchet ---------------------------------------------------------------------------------

def check_coverage():
    """SPECS must cover exactly the ``cosim=True`` blocks of ``test/registry.py`` VSPEC."""
    from test.registry import VSPEC
    variants = {
        "fir_complex_pipelined":     "fir_complex",
        "fir_decimator_pipelined":   "fir_decimator",
        "fir_interpolator_pipelined": "fir_interpolator",
        "frame_sync_pipelined":       "frame_sync",
        "rs_decoder_pipelined":       "rs_decoder",
        "viterbi_decoder_soft":      "viterbi_decoder",
        "viterbi_decoder_acs32":     "viterbi_decoder",
        "viterbi_decoder_soft_acs32": "viterbi_decoder",
        "parallel_fft_folded":       "parallel_fft",
        "parallel_fft_native_x2":    "parallel_fft",
        "parallel_fft_native_x4":    "parallel_fft",
        "parallel_fft_native_x4_dsp": "parallel_fft",
        "pfb_channelizer_fft":       "pfb_channelizer",
        "pfb_channelizer_2x":        "pfb_channelizer",
        "pfb_channelizer_fft_2x":    "pfb_channelizer",
        "carrier_loop_bpsk":         "carrier_loop",
        "carrier_loop_qpsk":         "carrier_loop",
        "carrier_loop_qpsk_pipelined": "carrier_loop",
        "timing_recovery_pipelined": "timing_recovery",
        "timing_recovery_gardner": "timing_recovery",
        "timing_recovery_gardner_pipelined": "timing_recovery",
        "clarke_three_wire":         "clarke",
        "sincos_cordic":             "sincos",
        "pi_controller_ref":         "pi_controller",
        "dq_controller_decoupling":  "dq_controller",
        "dither_ef2":                "dither",
        "log2_lut":                  "log2",
        "compressor_limiter":        "compressor",
        "compressor_gate":           "compressor",
    }
    eligible = {k for k, v in VSPEC.items() if v["cosim"]}
    missing  = eligible - set(SPECS)
    extra    = set(SPECS) - eligible - set(variants)
    invalid  = {name: base for name, base in variants.items()
                if name not in SPECS or base not in eligible}
    if missing or extra or invalid:
        raise RuntimeError(f"cosim spec/VSPEC mismatch: missing={sorted(missing)} "
                           f"extra={sorted(extra)} invalid_variants={invalid}")
