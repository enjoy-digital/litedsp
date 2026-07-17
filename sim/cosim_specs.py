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
    n, target = 300, 8000
    dut = LiteDSPAGC(data_width=16, with_csr=False, delayed_feedback=True)
    dut.target.reset = target
    cols = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: list(models.agc_model(
        c[0], c[1], target, delayed_feedback=True))

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

def spec_viterbi_decoder():
    from litedsp.comm.viterbi import LiteDSPViterbiDecoder
    n, prng = 448, random.Random(19)
    dut  = LiteDSPViterbiDecoder(with_csr=False, decision_memory=True,
        normalize_interval=16)
    data = _conv_symbols([prng.randint(0, 1) for _ in range(n)])
    for pos in range(73, n - 16, 29):
        data[pos] ^= 1 << ((pos // 29) & 1)                      # Exercise alternate survivors.
    return dut, [data], n - dut.traceback - 8, lambda c: [models.viterbi_model(c[0])]

def spec_viterbi_decoder_soft():
    from litedsp.comm.viterbi import LiteDSPViterbiDecoder
    n, llr_bits, prng = 384, 4, random.Random(20)
    dut = LiteDSPViterbiDecoder(llr_bits=llr_bits, with_csr=False,
        decision_memory=True, normalize_interval=16)
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

def spec_rs_decoder():
    from litedsp.comm.rs import LiteDSPRSDecoder
    n, k = 255, 251
    msg = _rand_cols(1, k, lo=0, hi=255, seed=43)[0]
    rx  = models.rs_encode_model(msg, n=n, k=k)
    rx[17]  ^= 0x53
    rx[211] ^= 0xa6
    dut   = LiteDSPRSDecoder(n=n, k=k, with_csr=False)
    first = [1] + [0]*(n - 1)
    last  = [0]*(n - 1) + [1]
    out_first = [1] + [0]*(k - 1)
    out_last  = [0]*(k - 1) + [1]
    return dut, [rx, first, last], k, lambda c: [
        models.rs_decode_model(c[0], n=n, k=k)[0], out_first, out_last], True, True

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

def spec_ldpc_decoder():
    from litedsp.comm.ldpc import LiteDSPLDPCDecoder, LDPC_K, LDPC_N
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
    dut  = LiteDSPLDPCDecoder(llr_bits=4, max_iters=8, with_csr=False)
    first = [int(k % LDPC_N == 0) for k in range(len(llrs))]
    last  = [int(k % LDPC_N == LDPC_N - 1) for k in range(len(llrs))]
    clear = [int(k == 3*LDPC_N) for k in range(len(llrs))]
    n_out = len(blocks)*LDPC_K
    out_first = [int(k % LDPC_K == 0) for k in range(n_out)]
    out_last  = [int(k % LDPC_K == LDPC_K - 1) for k in range(n_out)]
    return dut, [llrs, first, last, clear], n_out, lambda c: [
        expected, out_first, out_last], True, True, (dut.clear,)

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

def spec_frame_sync():
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
        peak_window=4, with_csr=False)
    dut.threshold.reset = threshold
    dut.offset.reset = 3
    fir_reset = [int(k == 196) for k in range(n)]
    clear  = [int(k == 180) for k in range(n)]
    cols  = [xi, xq, fir_reset, clear]
    n_out = n - dut.latency - 4
    return dut, cols, n_out, lambda c: list(models.frame_sync_model(
        c[0], c[1], sequence, threshold, frame_len=frame_len, offset=3)[:4]), \
        False, True, (dut.fir_r.reset, dut.clear_count)

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
    # Window *sinks* a plain stream (the frame counter is internal); it only *produces*
    # first/last frame markers, which the generic TB ignores. Blocks that would need
    # first/last driven on their sink (framed-stream input) are not in the cosim set yet;
    # TODO: extend stream_tb.cpp with first/last columns when one lands.
    from litedsp.analysis.window import LiteDSPWindow, window_coefficients
    n, n_win = 192, 64
    dut    = LiteDSPWindow(n=n_win, data_width=16, window="hann", with_csr=False)
    coeffs = window_coefficients(n_win, "hann")
    cols   = _rand_cols(2, n)
    return dut, cols, n - 4, lambda c: list(models.window_model(c[0], c[1], coeffs))

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
    feedback_pipeline=False):
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
        core_architecture=core_architecture, feedback_pipeline=feedback_pipeline, with_csr=False)
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

# Table --------------------------------------------------------------------------------------------

SPECS = {
    "nco":              spec_nco,
    "mixer":            spec_mixer,
    "fir_real":         spec_fir_real,
    "fir_complex":      spec_fir_complex,
    "fir_decimator":    spec_fir_decimator,
    "fir_interpolator": spec_fir_interpolator,
    "cic_decimator":    spec_cic_decimator,
    "cic_interpolator": spec_cic_interpolator,
    "iir_biquad":       spec_iir_biquad,
    "dc_blocker":       spec_dc_blocker,
    "moving_average":   spec_moving_average,
    "pfb_channelizer":  spec_pfb_channelizer,
    "pfb_channelizer_fft": spec_pfb_channelizer_fft,
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
    "puncturer":        spec_puncturer,
    "depuncturer":      spec_depuncturer,
    "block_interleaver": spec_block_interleaver,
    "block_deinterleaver": spec_block_deinterleaver,
    "rs_encoder":        spec_rs_encoder,
    "rs_decoder":        spec_rs_decoder,
    "ldpc_encoder":      spec_ldpc_encoder,
    "ldpc_decoder":      spec_ldpc_decoder,
    "correlator":       spec_correlator,
    "frame_sync":       spec_frame_sync,
    "dc_offset":        spec_dc_offset,
    "magnitude":        spec_magnitude,
    "window":           spec_window,
    "psd":              spec_psd,
    "parallel_fft":     spec_parallel_fft,
    "parallel_fft_folded":    spec_parallel_fft_folded,
    "parallel_fft_native_x2": spec_parallel_fft_native_x2,
    "parallel_fft_native_x4": spec_parallel_fft_native_x4,
    "welch":            spec_welch,
    "conjugate":        spec_conjugate,
    "swap_iq":          spec_swap_iq,
    "negate":           spec_negate,
    "combine":          spec_combine,
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
        "viterbi_decoder_soft":      "viterbi_decoder",
        "parallel_fft_folded":       "parallel_fft",
        "parallel_fft_native_x2":    "parallel_fft",
        "parallel_fft_native_x4":    "parallel_fft",
        "pfb_channelizer_fft":       "pfb_channelizer",
    }
    eligible = {k for k, v in VSPEC.items() if v["cosim"]}
    missing  = eligible - set(SPECS)
    extra    = set(SPECS) - eligible - set(variants)
    invalid  = {name: base for name, base in variants.items()
                if name not in SPECS or base not in eligible}
    if missing or extra or invalid:
        raise RuntimeError(f"cosim spec/VSPEC mismatch: missing={sorted(missing)} "
                           f"extra={sorted(extra)} invalid_variants={invalid}")
