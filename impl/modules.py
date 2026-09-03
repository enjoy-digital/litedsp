#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Registry of LiteDSP blocks to run through the FPGA implementation flows.

Each factory returns ``(dut, ios, clock_ns)``: the module, the set of port signals to expose as
top-level IOs (sink/source + controls), and the target clock period for fmax constraints.
"""

import os

import numpy as np

from litedsp.generation.nco          import LiteDSPNCO
from litedsp.generation.nco_parallel import LiteDSPParallelNCO
from litedsp.generation.cordic       import LiteDSPCORDIC
from litedsp.mixing.mixer            import LiteDSPMixer
from litedsp.mixing.mixer_parallel   import LiteDSPParallelMixer
from litedsp.mixing.ddc_parallel     import LiteDSPParallelDDC
from litedsp.filter.fir              import LiteDSPFIRFilter
from litedsp.filter.fir_parallel     import LiteDSPParallelFIRFilter
from litedsp.filter.cic_parallel     import LiteDSPParallelCICDecimator
from litedsp.mixing.ddc           import LiteDSPDDC
from litedsp.mixing.duc           import LiteDSPDUC
from litedsp.mixing.channelizer   import LiteDSPChannelizer
from litedsp.mixing.pfb_channelizer import LiteDSPPFBChannelizer
from litedsp.filter.fir           import LiteDSPFIRFilterComplex
from litedsp.filter.fir_poly      import LiteDSPFIRDecimator, LiteDSPFIRInterpolator
from litedsp.filter.cic           import LiteDSPCICDecimator, LiteDSPCICInterpolator
from litedsp.filter.halfband      import LiteDSPHalfbandDecimator
from litedsp.rate.farm            import LiteDSPResamplerFarm
from litedsp.filter.iir_biquad    import LiteDSPIIRBiquadCascade
from litedsp.filter.dc_blocker    import LiteDSPDCBlocker
from litedsp.filter.moving_average import LiteDSPMovingAverage
from litedsp.filter.farrow        import LiteDSPFarrowInterpolator
from litedsp.filter.equalizer     import LiteDSPLMSEqualizer
from litedsp.filter.design        import biquad_sos_quantize
from litedsp.level.gain           import LiteDSPGain
from litedsp.level.power          import LiteDSPPower
from litedsp.level.agc            import LiteDSPAGC
from litedsp.level.dpd            import LiteDSPDPD
from litedsp.level.cfr            import LiteDSPCFR
from litedsp.level.saturate       import LiteDSPSaturate
from litedsp.level.rms            import LiteDSPRMS
from litedsp.analysis.magnitude   import LiteDSPMagnitude
from litedsp.analysis.window      import LiteDSPWindow
from litedsp.analysis.fft         import LiteDSPFFT, LiteDSPInterleavedFFT
from litedsp.analysis.fft_iter    import LiteDSPFFTIter
from litedsp.analysis.fft_parallel import LiteDSPParallelFFT
from litedsp.analysis.reorder     import LiteDSPBitReverse
from litedsp.analysis.psd         import LiteDSPPSD
from litedsp.analysis.goertzel    import LiteDSPGoertzel
from litedsp.analysis.stats       import LiteDSPStats
from litedsp.analysis.histogram   import LiteDSPHistogram
from litedsp.stream.combine       import LiteDSPCombine
from litedsp.stream.fifo          import LiteDSPStreamFIFO
from litedsp.stream.adapt         import LiteDSPIQPack, LiteDSPIQUnpack
from litedsp.stream.csr_io        import LiteDSPCSRSource, LiteDSPCSRSink, LiteDSPNullSink
from litedsp.stream.framing       import LiteDSPStreamFramer
from litedsp.generation.pattern   import LiteDSPPatternSource
from litedsp.analysis.measure     import LiteDSPErrorCounter
from litedsp.comm.fm_demod        import LiteDSPFMDemod
from litedsp.comm.timing_recovery import LiteDSPTimingRecovery
from litedsp.comm.correlator      import LiteDSPCorrelator
from litedsp.comm.frame_sync      import LiteDSPFrameSync
from litedsp.comm.cfo_est         import LiteDSPCFOEstimator
from litedsp.comm.soft_demap      import LiteDSPSoftDemapper
from litedsp.comm.ofdm_eq         import LiteDSPOFDMEqualizer
from litedsp.comm.interleaver     import LiteDSPBlockInterleaver, LiteDSPBlockDeinterleaver
from litedsp.comm.puncture        import LiteDSPPuncturer, LiteDSPDepuncturer, PUNCTURE_3_4
from litedsp.comm.viterbi         import LiteDSPViterbiDecoder
from litedsp.comm.rs              import (
    LiteDSPRSEncoder, LiteDSPRSDecoder,
    LiteDSPCCSDSRSEncoder, LiteDSPCCSDSRSDecoder,
)
from litedsp.comm.ldpc            import LiteDSPLDPCEncoder, LiteDSPLDPCDecoder
from litedsp.comm.ldpc_parallel   import LiteDSPLDPCDecoderZParallel
from litedsp.motor.transforms     import (LiteDSPClarke, LiteDSPInverseClarke, LiteDSPSinCos,
    LiteDSPAngleRamp, LiteDSPPark, LiteDSPInversePark)
from litedsp.motor.pi             import LiteDSPPIController, LiteDSPDQController
from litedsp.motor.limiter        import LiteDSPSlewLimiter
from litedsp.motor.svpwm          import LiteDSPSVPWM
from litedsp.motor.pwm            import LiteDSPPWM
from litedsp.motor.sense          import LiteDSPSigmaDeltaFilter, LiteDSPOvercurrentTrip
from litedsp.motor.encoder        import LiteDSPQuadratureDecoder, LiteDSPHallDecoder
from litedsp.motor.observer       import LiteDSPAngleTracker, LiteDSPSMObserver
from litedsp.motor.resolver       import LiteDSPResolverDigital
from litedsp.motor.foc            import LiteDSPFOC
from litedsp.audio.level          import LiteDSPVolume, LiteDSPStereoMatrix
from litedsp.audio.dither         import LiteDSPDither
from litedsp.audio.eq             import LiteDSPAudioEQ
from litedsp.level.logdb          import LiteDSPLog2, LiteDSPExp2
from litedsp.audio.dynamics       import LiteDSPCompressor
from litedsp.audio.effects        import LiteDSPLFO, LiteDSPDelayLine, LiteDSPWetDryMix, LiteDSPReverb
from litedsp.stream.route         import LiteDSPTDMMux, LiteDSPTDMDemux
from litedsp.audio.meter          import LiteDSPPeakMeter, LiteDSPLoudness
from litedsp.audio.pdm            import LiteDSPSigmaDeltaModulator, LiteDSPSigmaDeltaDAC, LiteDSPPDMReceiver
from litedsp.audio.i2s            import LiteDSPI2SReceiver, LiteDSPI2STransmitter
from litedsp.radar.timing         import LiteDSPRangeGate
from litedsp.radar.compress       import LiteDSPPulseCompressor
from litedsp.radar.mti            import LiteDSPMTICanceller
from litedsp.radar.corner_turn    import LiteDSPCornerTurn
from litedsp.radar.doppler        import LiteDSPDopplerProcessor
from litedsp.radar.cfar           import LiteDSPCACFAR, LiteDSPOSCFAR
from litedsp.radar.clutter        import LiteDSPClutterMap
from litedsp.radar.cfar_2d        import LiteDSPCFAR2D
from litedsp.radar.detect         import LiteDSPPeakExtractor, LiteDSPTargetList
from litedsp.radar.track          import LiteDSPAlphaBetaTracker
from litedsp.radar.kalman         import LiteDSPKalmanTracker
from litedsp.filter.bitstream     import LiteDSPBitstreamDecimator
from litedsp.flow.ipcore          import LiteDSPFlowIPCore
from litedsp.gen                  import parse_config

# Helpers ------------------------------------------------------------------------------------------

def _eps(*endpoints):
    s = set()
    for ep in endpoints:
        s |= set(ep.flatten())
    return s

def _lowpass_sos(n_sections=3, fc=0.1, q=0.707):
    w0 = 2*np.pi*fc
    alpha = np.sin(w0)/(2*q)
    cw = np.cos(w0)
    sos = [[(1-cw)/2, 1-cw, (1-cw)/2, 1+alpha, -2*cw, 1-alpha]]*n_sections
    return biquad_sos_quantize(sos, frac_bits=14)

# Factories ----------------------------------------------------------------------------------------

def nco():
    d = LiteDSPNCO(data_width=16, with_csr=False)
    return d, {d.phase_inc} | _eps(d.source), 10.0

def nco_qw():
    d = LiteDSPNCO(data_width=16, quarter_wave=True, with_csr=False)
    return d, {d.phase_inc} | _eps(d.source), 10.0

def cordic_rot():
    d = LiteDSPCORDIC(data_width=16, mode="rotation", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def cordic_vec():
    d = LiteDSPCORDIC(data_width=16, mode="vectoring", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def mixer():
    d = LiteDSPMixer(data_width=16, with_csr=False)
    return d, {d.mode, d.bypass} | _eps(d.sink_a, d.sink_b, d.source), 10.0

def fir_complex():
    d = LiteDSPFIRFilterComplex(n_taps=32, data_width=16, with_csr=False)
    return d, {d.bypass} | _eps(d.sink, d.source), 10.0

def fir_decimator():
    d = LiteDSPFIRDecimator(n_taps=32, decimation=8, data_width=16, with_csr=False,
        architecture="pipelined")
    return d, {d.coeff_data, d.coeff_we, d.coeff_rst} | _eps(d.sink, d.source), 10.0

def fir_interpolator():
    d = LiteDSPFIRInterpolator(n_taps=32, interpolation=8, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def resampler_farm():
    d = LiteDSPResamplerFarm(n_channels=4, n_taps=32, decimation=8, data_width=16,
        with_csr=False, architecture="pipelined")
    return d, {d.coeff_data, d.coeff_we, d.coeff_rst} | _eps(d.source, *d.sinks), 10.0

def resampler_farm_banked():
    taps = [[(1 << 15) - 1] + [0]*31 for _ in range(4)]
    d = LiteDSPResamplerFarm(n_channels=4, n_taps=32, decimation=8, data_width=16,
        channel_coefficients=taps, with_csr=False, architecture="pipelined")
    return d, {d.coeff_data, d.coeff_we, d.coeff_rst, d.coeff_channel} | \
        _eps(d.source, *d.sinks), 10.0

def cic_decimator():
    d = LiteDSPCICDecimator(data_width=16, decimation=8, n_stages=4,
        with_csr=False, staged=True)
    return d, _eps(d.sink, d.source), 10.0

def cic_interpolator():
    d = LiteDSPCICInterpolator(data_width=16, interpolation=8, n_stages=4,
        with_csr=False, staged=True)
    return d, _eps(d.sink, d.source), 10.0

def halfband():
    d = LiteDSPHalfbandDecimator(n_taps=23, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def iir_biquad():
    sos, frac = _lowpass_sos(3)
    d = LiteDSPIIRBiquadCascade(data_width=16, sections=sos, frac_bits=frac, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def iir_biquad_folded():
    sos, frac = _lowpass_sos(3)
    d = LiteDSPIIRBiquadCascade(data_width=16, sections=sos, frac_bits=frac,
        architecture="folded", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def dc_blocker():
    d = LiteDSPDCBlocker(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def dc_blocker_real():
    d = LiteDSPDCBlocker(data_width=24, iq=False, precision_bits=8, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def tdm_mux():
    d = LiteDSPTDMMux(n_channels=2, data_width=24, with_csr=False)
    return d, _eps(*d.sinks, d.source), 10.0

def tdm_demux():
    d = LiteDSPTDMDemux(n_channels=2, data_width=24, with_csr=False)
    return d, _eps(d.sink, *d.sources), 10.0

def moving_average():
    d = LiteDSPMovingAverage(data_width=16, length_log2=5, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def farrow():
    d = LiteDSPFarrowInterpolator(data_width=16, with_csr=False)
    return d, {d.mu} | _eps(d.sink, d.source), 10.0

def gain():
    d = LiteDSPGain(data_width=16, with_csr=False)
    return d, {d.gain, d.shift, d.bypass, d.clear_sat} | _eps(d.sink, d.source), 10.0

def power():
    d = LiteDSPPower(data_width=16, with_csr=False)
    # Expose the measurement outputs too, or the whole datapath folds away (0-LUT entry).
    return d, {d.window_log2, d.power, d.update} | _eps(d.sink, d.source), 10.0

def agc():
    d = LiteDSPAGC(data_width=16, with_csr=False, feedback_delay=2)
    return d, {d.target} | _eps(d.sink, d.source), 10.0

def dpd():
    d = LiteDSPDPD(data_width=16, n_taps=3, lut_depth=64, coeff_frac=14, with_csr=False)
    return d, {d.lut_tap, d.lut_data, d.lut_we, d.lut_rst, d.bypass} | _eps(d.sink, d.source), 10.0

def cfr():
    d = LiteDSPCFR(data_width=16, pulse_span=16, with_csr=False)
    # Expose the counters too, or the detection path folds away.
    return d, {d.threshold, d.peak_count, d.missed_count, d.bypass} | _eps(d.sink, d.source), 10.0

def cfr_pipelined():
    d = LiteDSPCFR(data_width=16, pulse_span=16, architecture="pipelined", with_csr=False)
    return d, {d.threshold, d.peak_count, d.missed_count, d.bypass} | _eps(d.sink, d.source), 10.0

def saturate():
    d = LiteDSPSaturate(data_width=16, in_width=32, shift=15, with_csr=False)
    return d, {d.clear_sat} | _eps(d.sink, d.source), 10.0

def rms():
    d = LiteDSPRMS(data_width=16, window_log2=8, with_csr=False)
    return d, {d.window_log2} | _eps(d.sink, d.source), 10.0

def magnitude():
    d = LiteDSPMagnitude(data_width=16, method="approx", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def magnitude_cordic():
    d = LiteDSPMagnitude(data_width=16, method="cordic", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def combine():
    d = LiteDSPCombine(n_channels=4, data_width=16, with_csr=False)
    return d, {d.enable} | _eps(d.source, *d.sinks), 10.0

def window():
    d = LiteDSPWindow(256, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def fft():
    d = LiteDSPFFT(256, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def fft_folded():
    d = LiteDSPFFT(256, data_width=16, architecture="folded", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def fft_interleaved_x2():
    d = LiteDSPInterleavedFFT(256, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def fft_iter():
    d = LiteDSPFFTIter(256, data_width=16, with_csr=False, registered_butterfly=True)
    return d, _eps(d.sink, d.source), 10.0

def psd():
    d = LiteDSPPSD(256, data_width=16, avg_log2=4, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def bit_reverse():
    d = LiteDSPBitReverse(N=256, data_width=16, fft_latency=255, with_csr=False)
    return d, {d.filled} | _eps(d.sink, d.source), 10.0

def goertzel():
    d = LiteDSPGoertzel(64, 5, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def goertzel_folded():
    d = LiteDSPGoertzel(64, 5, data_width=16, architecture="folded", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def stats():
    d = LiteDSPStats(data_width=16, window_log2=8, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def histogram():
    d = LiteDSPHistogram(data_width=16, bits=8, window_log2=12, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def ddc():
    d = LiteDSPDDC(data_width=16, decimation=8, method="fir", with_csr=False,
        fir_architecture="pipelined")
    return d, {d.nco.phase_inc} | _eps(d.sink, d.source), 10.0

def duc():
    d = LiteDSPDUC(data_width=16, interpolation=8, method="fir", with_csr=False,
        fir_architecture="pipelined")
    return d, {d.nco.phase_inc} | _eps(d.sink, d.source), 10.0

def channelizer():
    d = LiteDSPChannelizer(n_channels=4, decimation=4, data_width=16, method="fir", with_csr=False,
        fir_architecture="pipelined")
    return d, _eps(d.sink, *d.sources), 10.0

def pfb_channelizer():
    d = LiteDSPPFBChannelizer(n_channels=4, taps_per_channel=8, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def pfb_channelizer_folded():
    d = LiteDSPPFBChannelizer(n_channels=4, taps_per_channel=8, data_width=16,
        architecture="folded", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def pfb_channelizer_fft():
    d = LiteDSPPFBChannelizer(n_channels=16, taps_per_channel=8, data_width=16,
        architecture="fft", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def pfb_channelizer_fft_2x():
    d = LiteDSPPFBChannelizer(n_channels=16, taps_per_channel=8, data_width=16,
        architecture="fft", oversampling=2, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def lms_equalizer():
    d = LiteDSPLMSEqualizer(n_taps=7, data_width=16, with_csr=False)
    return d, {d.train, d.mode, d.cma_r2, d.dd_level} | _eps(d.sink, d.source), 12.0

def lms_equalizer_pipelined():
    d = LiteDSPLMSEqualizer(n_taps=7, data_width=16, architecture="pipelined",
        update_pipeline=True, with_csr=False)
    # A small implementation margin keeps the reviewed 100 MHz target out of route noise.
    return d, {d.train, d.mode, d.cma_r2, d.dd_level} | _eps(d.sink, d.source), 9.8

def timing_recovery():
    d = LiteDSPTimingRecovery(data_width=16, architecture="pipelined", with_csr=False)
    return d, _eps(d.sink, d.source), 12.0

def fm_demod():
    d = LiteDSPFMDemod(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def correlator():
    d = LiteDSPCorrelator([1, 1, 1, -1, -1, 1, -1], data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def frame_sync():
    d = LiteDSPFrameSync([1, 1, 1, -1, -1, 1, -1], data_width=16, frame_len=64,
        with_csr=False, architecture="pipelined")
    return d, {d.threshold, d.offset, d.detected} | _eps(d.sink, d.source), 10.0

def cfo_estimator():
    d = LiteDSPCFOEstimator(data_width=16, delay=16, span_log2=8, with_csr=False)
    return d, {d.angle, d.phase_inc_correction, d.estimate_ready} | _eps(d.sink, d.source), 10.0

def soft_demapper():
    d = LiteDSPSoftDemapper(bits_per_axis=1, spacing=8000, llr_bits=4, data_width=16,
        with_csr=False)
    return d, {d.llr_scale} | _eps(d.sink, d.source), 10.0

def ofdm_equalizer():
    d = LiteDSPOFDMEqualizer(fft_size=64, data_width=16, with_csr=False)
    return d, {d.train, d.ref_data, d.ref_we, d.ref_rst} | _eps(d.sink, d.source), 10.0

def puncturer():
    d = LiteDSPPuncturer(pattern=PUNCTURE_3_4, n=2, with_csr=False)
    return d, {d.phase_rst} | _eps(d.sink, d.source), 8.0

def depuncturer():
    d = LiteDSPDepuncturer(pattern=PUNCTURE_3_4, n=2, llr_bits=4, with_csr=False)
    return d, {d.phase_rst} | _eps(d.sink, d.source), 8.0

def viterbi_decoder():
    d = LiteDSPViterbiDecoder(with_csr=False, decision_memory=True,
        normalize_interval=16)                               # Hard-decision, K=7 (171, 133).
    return d, _eps(d.sink, d.source), 10.0

def viterbi_decoder_soft():
    d = LiteDSPViterbiDecoder(llr_bits=4, with_csr=False, decision_memory=True,
        normalize_interval=16)                               # Soft-decision, 4-bit LLRs.
    return d, _eps(d.sink, d.source), 10.0

def viterbi_decoder_acs32():
    d = LiteDSPViterbiDecoder(with_csr=False, decision_memory=True,
        normalize_interval=16, acs_parallelism=32)            # Two-phase 32-ACS schedule.
    return d, _eps(d.sink, d.source), 10.0

def viterbi_decoder_soft_acs32():
    d = LiteDSPViterbiDecoder(llr_bits=4, with_csr=False, decision_memory=True,
        normalize_interval=16, acs_parallelism=32)
    return d, _eps(d.sink, d.source), 10.0

def block_interleaver():
    d = LiteDSPBlockInterleaver(rows=5, cols=255, width=8, with_csr=False)   # CCSDS I=5.
    return d, {d.filled} | _eps(d.sink, d.source), 8.0

def block_deinterleaver():
    d = LiteDSPBlockDeinterleaver(rows=5, cols=255, width=8, with_csr=False)
    return d, {d.filled} | _eps(d.sink, d.source), 8.0

def rs_encoder():
    d = LiteDSPRSEncoder(with_csr=False)                     # RS(255,223), t=16.
    return d, _eps(d.sink, d.source), 10.0

def rs_decoder():
    d = LiteDSPRSDecoder(with_csr=False, architecture="pipelined")  # RS(255,223), t=16.
    return d, {d.corrected, d.corrected_total, d.uncorrectable, d.uncorrectable_count,
               d.clear} | _eps(d.sink, d.source), 12.0

def ccsds_rs_encoder():
    d = LiteDSPCCSDSRSEncoder(with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def ccsds_rs_decoder():
    d = LiteDSPCCSDSRSDecoder(with_csr=False, architecture="pipelined")
    return d, {d.corrected, d.corrected_total, d.uncorrectable, d.uncorrectable_count,
               d.clear} | _eps(d.sink, d.source), 12.0

def ldpc_encoder():
    d = LiteDSPLDPCEncoder(with_csr=False)                   # 802.11n (648, 324), z=27.
    return d, _eps(d.sink, d.source), 10.0

def ldpc_decoder():
    d = LiteDSPLDPCDecoder(llr_bits=4, max_iters=8, with_csr=False)  # Layered min-sum.
    return d, {d.iterations, d.parity_ok, d.failures, d.clear} | _eps(d.sink, d.source), 12.0

def ldpc_decoder_z_parallel():
    d = LiteDSPLDPCDecoderZParallel(llr_bits=4, max_iters=8, with_csr=False)
    return d, {d.iterations, d.parity_ok, d.failures, d.clear} | _eps(d.sink, d.source), 10.0

def ldpc_decoder_lanes_3():
    d = LiteDSPLDPCDecoderZParallel(
        llr_bits=4, max_iters=8, parallelism=3, with_csr=False)
    return d, {d.iterations, d.parity_ok, d.failures, d.clear} | _eps(d.sink, d.source), 10.0

def ldpc_decoder_lanes_9():
    d = LiteDSPLDPCDecoderZParallel(
        llr_bits=4, max_iters=8, parallelism=9, with_csr=False)
    return d, {d.iterations, d.parity_ok, d.failures, d.clear} | _eps(d.sink, d.source), 10.0

def stream_fifo():
    d = LiteDSPStreamFIFO(depth=16, data_width=16, with_csr=False)
    return d, {d.level, d.overflow} | _eps(d.sink, d.source), 8.0

def iq_pack():
    d = LiteDSPIQPack(ratio=4, data_width=16)
    return d, _eps(d.sink, d.source), 8.0

def iq_unpack():
    d = LiteDSPIQUnpack(ratio=4, data_width=16)
    return d, _eps(d.sink, d.source), 8.0

def csr_source():
    d = LiteDSPCSRSource(data_width=16, with_csr=False)
    return d, {d.i, d.q, d.push} | _eps(d.source), 8.0

def csr_sink():
    d = LiteDSPCSRSink(data_width=16, with_csr=False)
    return d, {d.last_i, d.last_q, d.count, d.clear} | _eps(d.sink), 8.0

def null_sink():
    d = LiteDSPNullSink(data_width=16, with_csr=False)
    return d, {d.count, d.clear} | _eps(d.sink), 8.0

def pattern_source():
    d = LiteDSPPatternSource(data_width=16, with_csr=False)
    return d, {d.mode, d.const_i, d.const_q} | _eps(d.source), 8.0

def error_counter():
    d = LiteDSPErrorCounter(data_width=16, with_csr=False)
    return d, {d.errors, d.total, d.clear} | _eps(d.sink_ref, d.sink_rx), 8.0

def framer():
    d = LiteDSPStreamFramer(length=256, data_width=16, with_csr=False)
    return d, {d.length} | _eps(d.sink, d.source), 8.0

# Parallel (multi-sample-per-cycle) variants. Coefficients are exposed as ports on the FIRs so
# the multipliers stay runtime-variable (not const-folded) and the DSP scaling vs n_samples is
# honest; these are synthesis-resource entries (port count exceeds device pins for full P&R).

def fir():
    d = LiteDSPFIRFilter(n_taps=32, data_width=16)
    return d, set(d.coeffs) | _eps(d.sink, d.source), 10.0

def _parallel_nco(n):
    d = LiteDSPParallelNCO(n_samples=n, data_width=16, with_csr=False)
    return d, {d.phase_inc} | _eps(d.source), 10.0

def _parallel_mixer(n):
    d = LiteDSPParallelMixer(n_samples=n, data_width=16, with_csr=False)
    return d, {d.mode} | _eps(d.sink_a, d.sink_b, d.source), 10.0

def _parallel_fir(n):
    d = LiteDSPParallelFIRFilter(n_samples=n, n_taps=32, data_width=16)
    return d, set(d.coeffs) | _eps(d.sink, d.source), 10.0

def nco_parallel_x2():   return _parallel_nco(2)
def nco_parallel_x4():   return _parallel_nco(4)
def mixer_parallel_x2(): return _parallel_mixer(2)
def mixer_parallel_x4(): return _parallel_mixer(4)
def fir_parallel_x2():   return _parallel_fir(2)
def fir_parallel_x4():   return _parallel_fir(4)

def cic_parallel_x2():
    d = LiteDSPParallelCICDecimator(n_samples=2, data_width=16, decimation=8, n_stages=4,
        with_csr=False, staged=True)
    return d, _eps(d.sink, d.source), 10.0

def cic_parallel_x4():
    d = LiteDSPParallelCICDecimator(n_samples=4, data_width=16, decimation=8, n_stages=4,
        with_csr=False, staged=True)
    return d, _eps(d.sink, d.source), 10.0

def ddc_parallel_x4():
    d = LiteDSPParallelDDC(n_samples=4, data_width=16, decimation=8, with_csr=False)
    return d, {d.nco.phase_inc} | _eps(d.sink, d.source), 10.0

def fft_parallel_x2():
    d = LiteDSPParallelFFT(N=256, data_width=16, with_csr=False)   # Same N as the serial fft entry.
    return d, _eps(d.sink, d.source), 10.0

def fft_parallel_x2_folded():
    d = LiteDSPParallelFFT(N=256, data_width=16, core_architecture="folded", with_csr=False)
    # Two full cores put ECP5 routing near the utilization cliff; constrain at its measured
    # operating class so nextpnr can complete instead of chasing the serial core's 100 MHz.
    return d, _eps(d.sink, d.source), 14.3

def fft_parallel_native_x2():
    d = LiteDSPParallelFFT(N=256, n_samples=2, data_width=16, implementation="native",
        feedback_pipeline=True, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def fft_parallel_native_x4():
    d = LiteDSPParallelFFT(N=256, n_samples=4, data_width=16, implementation="native",
        feedback_pipeline=True, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def fft_parallel_native_x4_dsp():
    d = LiteDSPParallelFFT(N=256, n_samples=4, data_width=16, implementation="native",
        feedback_pipeline=True, complex_multiplier="three", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def ddc_ip():
    """Complete generated DDC IP: AXI-Stream datapath plus AXI-Lite CSR bridge."""
    config = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "examples", "ddc_core.yml")
    nl, core_config = parse_config(config)
    core_config.pop("name", None)
    d = LiteDSPFlowIPCore(nl, **core_config)
    return d, d.io_signals(), nl.clock_ns

def qpsk_receiver_ip():
    """Complete generated QPSK receiver IP with AXI-Stream and AXI-Lite interfaces."""
    config = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "examples", "qpsk_receiver_core.yml")
    nl, core_config = parse_config(config)
    core_config.pop("name", None)
    d = LiteDSPFlowIPCore(nl, **core_config)
    return d, d.io_signals(), nl.clock_ns

# Motor control.
# --------------
def clarke():
    d = LiteDSPClarke(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def inverse_clarke():
    d = LiteDSPInverseClarke(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def sincos():
    d = LiteDSPSinCos(data_width=16, angle_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def sincos_cordic():
    d = LiteDSPSinCos(data_width=16, angle_width=16, method="cordic", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def angle_ramp():
    d = LiteDSPAngleRamp(angle_width=16, phase_bits=32, with_csr=False)
    return d, {d.phase_inc} | _eps(d.source), 10.0

def park():
    d = LiteDSPPark(data_width=16, angle_width=16, with_csr=False)
    return d, _eps(d.sink, d.sink_angle, d.source), 10.0

def inverse_park():
    d = LiteDSPInversePark(data_width=16, angle_width=16, with_csr=False)
    return d, _eps(d.sink, d.sink_angle, d.source), 10.0

def pi_controller():
    d = LiteDSPPIController(data_width=16, with_csr=False)
    return d, {d.setpoint, d.kp, d.ki, d.limit, d.feedforward, d.open_loop, d.clear, d.clear_sat,
               d.integral, d.saturated} | _eps(d.sink, d.source), 10.0

def dq_controller():
    d = LiteDSPDQController(data_width=16, with_csr=False)
    return d, {d.setpoint_d, d.setpoint_q, d.kp_d, d.ki_d, d.kp_q, d.ki_q, d.limit, d.voltage_d,
               d.voltage_q, d.open_loop, d.clear, d.clear_sat, d.saturated} | \
           _eps(d.sink, d.source), 10.0

def dq_controller_decoupling():
    d = LiteDSPDQController(data_width=16, decoupling=True, with_csr=False)
    return d, {d.setpoint_d, d.setpoint_q, d.kp_d, d.ki_d, d.kp_q, d.ki_q, d.limit, d.voltage_d,
               d.voltage_q, d.open_loop, d.clear, d.clear_sat, d.saturated, d.speed, d.l_pu,
               d.psi_pu} | _eps(d.sink, d.source), 10.0

def slew_limiter():
    d = LiteDSPSlewLimiter(data_width=16, with_csr=False)
    return d, {d.rate, d.bypass} | _eps(d.sink, d.source), 10.0

def svpwm():
    d = LiteDSPSVPWM(data_width=16, with_csr=False)
    return d, {d.injection} | _eps(d.sink, d.source), 10.0

def bitstream_decimator():
    d = LiteDSPBitstreamDecimator(data_width=24, decimation=64, n_stages=4, with_csr=False)
    return d, {d.rate, d.shift} | _eps(d.sink, d.source), 10.0

def sigma_delta_filter():
    d = LiteDSPSigmaDeltaFilter(data_width=16, with_csr=False)
    return d, {d.rate, d.shift, d.threshold, d.clear, d.overcurrent} | set(d.fast_value) | \
           _eps(d.source, *d.sinks), 10.0

def overcurrent_trip():
    d = LiteDSPOvercurrentTrip(data_width=16, with_csr=False)
    return d, {d.threshold, d.clear, d.fault, d.phase, d.count} | _eps(d.sink, d.source), 10.0

def quadrature_decoder():
    d = LiteDSPQuadratureDecoder(with_csr=False)
    return d, {d.a, d.b, d.z, d.sample, d.counts_per_rev, d.pole_pairs, d.angle_scale,
               d.angle_offset, d.window, d.invert, d.index_enable, d.clear, d.position, d.epos,
               d.direction, d.speed, d.index_seen, d.error, d.overrun} | _eps(d.source), 10.0

def hall_decoder():
    d = LiteDSPHallDecoder(with_csr=False)
    return d, {d.hall, d.sample, d.angle_offset, d.invert, d.clear, d.sector, d.direction,
               d.period, d.speed, d.error, d.stall, d.overrun} | _eps(d.source), 10.0

def angle_tracker():
    d = LiteDSPAngleTracker(angle_width=16, with_csr=False)
    return d, {d.kp_shift, d.ki_shift, d.speed, d.error} | _eps(d.sink, d.source), 10.0

def smo_observer():
    d = LiteDSPSMObserver(data_width=16, angle_width=16, with_csr=False)
    return d, {d.g_v, d.g_r, d.k_sm, d.lpf_shift, d.clear, d.emf_alpha, d.emf_beta} | \
           _eps(d.sink_i, d.sink_v, d.source), 10.0

def resolver():
    d = LiteDSPResolverDigital(data_width=16, angle_width=16, with_csr=False)
    return d, {d.phase_offset, d.kp_shift, d.ki_shift, d.speed, d.raw_angle, d.raw_mag} | \
           _eps(d.sink, d.source, d.source_exc), 10.0

def foc():
    d = LiteDSPFOC(data_width=16, angle_width=16, with_csr=False)
    dq = d.dq
    return d, {dq.setpoint_d, dq.setpoint_q, dq.kp_d, dq.ki_d, dq.kp_q, dq.ki_q, dq.limit,
               dq.voltage_d, dq.voltage_q, dq.open_loop, dq.clear, dq.clear_sat, dq.saturated,
               d.svpwm.injection, d.speed} | _eps(d.sink, d.sink_angle, d.source), 10.0

def pwm():
    d = LiteDSPPWM(data_width=16, period_width=16, dead_time_width=8, with_csr=False)
    return d, {d.pwm_h, d.pwm_l, d.trigger, d.fault, d.period, d.dead_time, d.enable,
               d.fault_clear, d.missed_clear, d.trigger_count, d.trigger_direction,
               d.fault_latched, d.missed} | _eps(d.sink), 10.0

# Audio.
# ------
def volume():
    d = LiteDSPVolume(data_width=24, n_channels=2, with_csr=False)
    return d, {d.mute, d.ramp_enable, d.bypass, d.clear_sat, d.sat} | set(d.gains) | \
           _eps(d.sink, d.source), 10.0

def stereo_matrix():
    d = LiteDSPStereoMatrix(data_width=24, with_csr=False)
    return d, {d.a, d.b, d.c, d.d, d.bypass, d.clear_sat, d.sat, d.sequence_error} | \
           _eps(d.sink, d.source), 10.0

def dither():
    d = LiteDSPDither(data_width=24, out_width=16, n_channels=2, shaping="ef2", with_csr=False)
    return d, {d.dither_enable, d.shaping_enable, d.bypass, d.clear_sat, d.sat} | \
           _eps(d.sink, d.source), 10.0

def audio_eq():
    d = LiteDSPAudioEQ(data_width=24, n_bands=3, n_channels=2, with_csr=False)
    return d, {d.band_enable, d.bypass, d.coeff_index, d.coeff_value, d.coeff_we, d.coeff_commit,
               d.commit_pending, d.clear_sat, d.sat} | _eps(d.sink, d.source), 10.0

def log2_lut():
    d = LiteDSPLog2(in_width=32, frac_bits=8, lut=True, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def exp2():
    d = LiteDSPExp2(with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def _compressor_ios(d):
    return {d.threshold, d.slope_above, d.slope_below, d.attack, d.release, d.gr_max, d.makeup,
            d.detector, d.rms_shift, d.stereo_link, d.bypass, d.clear_sat, d.sat,
            d.gain_reduction} | _eps(d.sink, d.source)

def compressor():
    d = LiteDSPCompressor(data_width=24, n_channels=2, with_csr=False)
    return d, _compressor_ios(d), 10.0

def limiter():
    d = LiteDSPCompressor(data_width=24, n_channels=2, lookahead=32, preset="limiter", with_csr=False)
    return d, _compressor_ios(d), 10.0

def lfo():
    d = LiteDSPLFO(with_csr=False)
    return d, {d.phase_inc, d.shape, d.amplitude} | _eps(d.source), 10.0

def delay_line():
    d = LiteDSPDelayLine(data_width=24, n_channels=2, max_delay=4096, with_csr=False)
    return d, {d.delay, d.feedback, d.damping, d.wet, d.dry, d.bypass, d.clear_sat, d.sat} | \
           _eps(d.sink, d.source), 10.0

def chorus():
    d = LiteDSPDelayLine(data_width=24, n_channels=2, max_delay=512, modulation=True, with_csr=False)
    return d, {d.delay, d.feedback, d.damping, d.wet, d.dry, d.mod_depth, d.bypass, d.clear_sat,
               d.sat} | _eps(d.sink, d.sink_mod, d.source), 10.0

def wet_dry_mix():
    d = LiteDSPWetDryMix(data_width=24, with_csr=False)
    return d, {d.wet, d.dry, d.clear_sat, d.sat} | _eps(d.sink_dry, d.sink_wet, d.source), 10.0

def reverb():
    d = LiteDSPReverb(data_width=24, n_channels=2, with_csr=False)
    return d, {d.room_size, d.damping, d.allpass_gain, d.wet, d.dry} | _eps(d.sink, d.source), 10.0

def peak_meter():
    d = LiteDSPPeakMeter(data_width=24, n_channels=2, with_csr=False)
    return d, {d.decay_shift, d.clip_threshold, d.clear, d.clip, *d.peak, *d.hold, *d.clip_count,
               *d.peak_log2} | _eps(d.sink, d.source), 10.0

def loudness():
    d = LiteDSPLoudness(data_width=24, n_channels=2, with_csr=False)
    return d, {d.clear, d.sum_sq, d.hop_count, d.update, d.overrun} | _eps(d.sink, d.source), 10.0

def sigma_delta_mod():
    d = LiteDSPSigmaDeltaModulator(data_width=24, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def sigma_delta_dac():
    d = LiteDSPSigmaDeltaDAC(data_width=24, n_channels=2, with_csr=False)
    return d, {d.pdm_out, d.pdm_clk, d.underrun, d.clear} | _eps(d.sink), 10.0

def pdm_rx():
    d = LiteDSPPDMReceiver(data_width=24, n_channels=2, with_csr=False)
    return d, {d.mclk, d.mdat, d.overrun, d.clear} | _eps(d.source), 10.0

def i2s_rx():
    d = LiteDSPI2SReceiver(data_width=24, with_csr=False)
    return d, {d.bclk, d.lrck, d.sdata, d.enable, d.clear, d.overrun} | _eps(d.source), 10.0

def i2s_tx():
    d = LiteDSPI2STransmitter(data_width=24, with_csr=False)
    return d, {d.bclk, d.lrck, d.sdata, d.enable, d.clear, d.underrun} | _eps(d.sink), 10.0

def range_gate():
    d = LiteDSPRangeGate(data_width=16, with_csr=False)
    return d, {d.pri, d.gate_start, d.gate_len, d.pulse_width, d.n_pulses_cpi, d.enable, d.single, d.trigger,
               d.tx, d.rx_gate, d.cpi_start, d.running, d.pulse_index, d.pulse_count} | _eps(d.sink, d.source), 10.0

def corner_turn():
    d = LiteDSPCornerTurn(n_range_bins=64, n_pulses=16, with_csr=False)
    return d, {d.clear, d.frame_error, d.filled} | _eps(d.sink, d.source), 10.0

def ca_cfar():
    d = LiteDSPCACFAR(n_train=8, n_guard=2, with_csr=False)
    return d, {d.alpha, d.mode, d.threshold_min, d.detections} | _eps(d.sink, d.source), 10.0

def os_cfar():
    d = LiteDSPOSCFAR(n_train=4, n_guard=2, with_csr=False)
    return d, {d.alpha, d.rank, d.threshold_min, d.detections} | _eps(d.sink, d.source), 10.0

def clutter_map():
    d = LiteDSPClutterMap(with_csr=False)
    return d, {d.alpha, d.threshold_min, d.learn_all, d.freeze, d.clear, d.detections, d.scans} | _eps(d.sink, d.source), 10.0

def cfar_2d():
    d = LiteDSPCFAR2D(with_csr=False)
    return d, {d.alpha, d.threshold_min, d.clear, d.frame_error, d.detections} | _eps(d.sink, d.source), 10.0

def cfar_2d_wide():
    d = LiteDSPCFAR2D(n_train=(6, 3), with_csr=False)
    return d, {d.alpha, d.threshold_min, d.clear, d.frame_error, d.detections} | _eps(d.sink, d.source), 10.0

def peak_extractor():
    d = LiteDSPPeakExtractor(with_csr=False)
    return d, {d.local_max, d.interpolate, d.clear, d.frame_error, d.count, d.last_count, d.cpi_count, d.cpi_done} | _eps(d.sink, d.source), 10.0

def target_list():
    d = LiteDSPTargetList(with_csr=False)
    return d, {d.clear, d.overflow, d.dropped, d.cpi_count, d.sealed, d.rd_index, d.rd_range, d.rd_doppler, d.rd_data, d.rd_count} | _eps(d.sink, d.source), 10.0

def kalman_tracker():
    d = LiteDSPKalmanTracker(with_csr=False)
    return d, {d.q, d.r, d.p_vel0, d.cov_sat, d.clear_sat, d.gate_r, d.gate_d, d.confirm_hits, d.max_misses, d.emit_tentative,
               d.clear, d.active, d.confirmed, d.dropped, d.cpi_count, d.cpi_done} | _eps(d.sink, d.source), 10.0

def alpha_beta_tracker():
    d = LiteDSPAlphaBetaTracker(with_csr=False)
    return d, {d.alpha, d.beta, d.gate_r, d.gate_d, d.confirm_hits, d.max_misses, d.emit_tentative, d.clear, d.active,
               d.confirmed, d.dropped, d.cpi_count, d.cpi_done} | _eps(d.sink, d.source), 10.0

def doppler():
    d = LiteDSPDopplerProcessor(n_pulses=16, with_csr=False)
    return d, {d.clear, d.frame_error} | _eps(d.sink, d.source), 10.0

def mti():
    d = LiteDSPMTICanceller(n_range_bins=256, order=3, with_csr=False)
    return d, {d.mode, d.bypass} | _eps(d.sink, d.source), 10.0

def pulse_compressor():
    d = LiteDSPPulseCompressor(pulse_len=16, with_csr=False)
    return d, {d.clear, d.saturated} | _eps(d.sink, d.source), 10.0

def pulse_compressor_mac():
    d = LiteDSPPulseCompressor(pulse_len=32, fir_architecture="mac", n_macs=4, with_csr=False)
    return d, {d.clear, d.saturated} | _eps(d.sink, d.source), 10.0

# Registry -----------------------------------------------------------------------------------------

REGISTRY = {
    "nco": nco, "nco_qw": nco_qw, "cordic_rot": cordic_rot, "cordic_vec": cordic_vec,
    "mixer": mixer, "fir_complex": fir_complex, "fir_decimator": fir_decimator,
    "fir_interpolator": fir_interpolator, "resampler_farm": resampler_farm,
    "resampler_farm_banked": resampler_farm_banked,
    "cic_decimator": cic_decimator,
    "cic_interpolator": cic_interpolator, "halfband": halfband, "iir_biquad": iir_biquad,
    "iir_biquad_folded": iir_biquad_folded,
    "dc_blocker": dc_blocker, "dc_blocker_real": dc_blocker_real, "tdm_mux": tdm_mux,
    "tdm_demux": tdm_demux, "moving_average": moving_average, "farrow": farrow,
    "gain": gain, "power": power, "agc": agc, "dpd": dpd, "cfr": cfr,
    "cfr_pipelined": cfr_pipelined, "saturate": saturate, "rms": rms,
    "magnitude": magnitude, "magnitude_cordic": magnitude_cordic, "combine": combine,
    "window": window, "fft": fft, "fft_folded": fft_folded,
    "fft_interleaved_x2": fft_interleaved_x2, "fft_iter": fft_iter, "psd": psd, "bit_reverse": bit_reverse,
    "goertzel": goertzel, "goertzel_folded": goertzel_folded,
    "stats": stats, "histogram": histogram, "ddc": ddc, "duc": duc, "channelizer": channelizer,
    "ddc_ip": ddc_ip, "qpsk_receiver_ip": qpsk_receiver_ip,
    "pfb_channelizer": pfb_channelizer, "pfb_channelizer_folded": pfb_channelizer_folded,
    "pfb_channelizer_fft": pfb_channelizer_fft,
    "pfb_channelizer_fft_2x": pfb_channelizer_fft_2x,
    "lms_equalizer": lms_equalizer, "lms_equalizer_pipelined": lms_equalizer_pipelined,
    "timing_recovery": timing_recovery, "fm_demod": fm_demod,
    "correlator": correlator, "frame_sync": frame_sync, "cfo_estimator": cfo_estimator,
    "soft_demapper": soft_demapper, "ofdm_equalizer": ofdm_equalizer,
    "puncturer": puncturer, "depuncturer": depuncturer,
    "viterbi_decoder": viterbi_decoder, "viterbi_decoder_soft": viterbi_decoder_soft,
    "viterbi_decoder_acs32": viterbi_decoder_acs32,
    "viterbi_decoder_soft_acs32": viterbi_decoder_soft_acs32,
    "block_interleaver": block_interleaver, "block_deinterleaver": block_deinterleaver,
    "rs_encoder": rs_encoder, "rs_decoder": rs_decoder,
    "ccsds_rs_encoder": ccsds_rs_encoder, "ccsds_rs_decoder": ccsds_rs_decoder,
    "ldpc_encoder": ldpc_encoder, "ldpc_decoder": ldpc_decoder,
    "ldpc_decoder_z_parallel": ldpc_decoder_z_parallel,
    "ldpc_decoder_lanes_3": ldpc_decoder_lanes_3,
    "ldpc_decoder_lanes_9": ldpc_decoder_lanes_9,
    "stream_fifo": stream_fifo, "iq_pack": iq_pack, "iq_unpack": iq_unpack,
    "csr_source": csr_source, "csr_sink": csr_sink, "null_sink": null_sink,
    "pattern_source": pattern_source, "error_counter": error_counter, "framer": framer,
    "fir": fir,
    "nco_parallel_x2": nco_parallel_x2, "nco_parallel_x4": nco_parallel_x4,
    "mixer_parallel_x2": mixer_parallel_x2, "mixer_parallel_x4": mixer_parallel_x4,
    "fir_parallel_x2": fir_parallel_x2, "fir_parallel_x4": fir_parallel_x4,
    "cic_parallel_x2": cic_parallel_x2, "cic_parallel_x4": cic_parallel_x4,
    "ddc_parallel_x4": ddc_parallel_x4,
    "fft_parallel_x2": fft_parallel_x2,
    "fft_parallel_x2_folded": fft_parallel_x2_folded,
    "fft_parallel_native_x2": fft_parallel_native_x2,
    "fft_parallel_native_x4": fft_parallel_native_x4,
    "fft_parallel_native_x4_dsp": fft_parallel_native_x4_dsp,
    "clarke": clarke, "inverse_clarke": inverse_clarke, "sincos": sincos,
    "sincos_cordic": sincos_cordic, "angle_ramp": angle_ramp, "park": park,
    "inverse_park": inverse_park, "pi_controller": pi_controller,
    "dq_controller": dq_controller, "dq_controller_decoupling": dq_controller_decoupling,
    "slew_limiter": slew_limiter, "svpwm": svpwm, "pwm": pwm,
    "bitstream_decimator": bitstream_decimator, "sigma_delta_filter": sigma_delta_filter,
    "overcurrent_trip": overcurrent_trip, "quadrature_decoder": quadrature_decoder,
    "hall_decoder": hall_decoder, "angle_tracker": angle_tracker, "smo_observer": smo_observer,
    "resolver": resolver, "foc": foc,
    "volume": volume, "stereo_matrix": stereo_matrix, "dither": dither, "audio_eq": audio_eq,
    "log2_lut": log2_lut, "exp2": exp2, "compressor": compressor, "limiter": limiter,
    "lfo": lfo, "delay_line": delay_line, "chorus": chorus, "wet_dry_mix": wet_dry_mix,
    "reverb": reverb, "peak_meter": peak_meter, "loudness": loudness,
    "sigma_delta_mod": sigma_delta_mod, "sigma_delta_dac": sigma_delta_dac, "pdm_rx": pdm_rx,
    "i2s_rx": i2s_rx, "i2s_tx": i2s_tx,
    "range_gate": range_gate, "pulse_compressor": pulse_compressor, "pulse_compressor_mac": pulse_compressor_mac,
    "mti": mti, "corner_turn": corner_turn, "doppler": doppler, "ca_cfar": ca_cfar, "cfar_2d": cfar_2d, "os_cfar": os_cfar, "clutter_map": clutter_map, "cfar_2d_wide": cfar_2d_wide, "peak_extractor": peak_extractor, "target_list": target_list, "alpha_beta_tracker": alpha_beta_tracker, "kalman_tracker": kalman_tracker,
}

# Subset for the slower full place-&-route flows.
PNR_SUBSET = ["cfar_2d", "doppler", "nco", "mixer", "fir_complex", "fir_decimator", "cic_decimator",
              "cic_interpolator", "iir_biquad", "fft", "fft_iter", "cordic_vec", "ddc",
              "duc", "channelizer", "frame_sync", "resampler_farm", "ldpc_decoder", "viterbi_decoder", "viterbi_decoder_soft",
              "viterbi_decoder_acs32",
              "rs_decoder", "ccsds_rs_decoder",
              "cic_parallel_x2", "cic_parallel_x4", "mixer_parallel_x2", "farrow", "window",
              "fft_folded", "fft_interleaved_x2", "fft_parallel_x2",
              "fft_parallel_native_x2",
              "goertzel_folded", "iir_biquad_folded", "pfb_channelizer_folded",
              "pfb_channelizer_fft",
              "pfb_channelizer_fft_2x",
              "ldpc_decoder_lanes_9",
              "cfr_pipelined", "lms_equalizer_pipelined", "timing_recovery", "agc", "ddc_ip",
              "qpsk_receiver_ip", "foc", "audio_eq", "compressor"]

# Capacity-cliff routes kept out of the bounded push/PR matrix. Nightly CI gives these wide
# configurations an independent runner and a longer timeout so they cannot starve the sentinels.
PNR_STRESS = ["fft_parallel_native_x4", "fft_parallel_native_x4_dsp",
              "ldpc_decoder_z_parallel"]

# Marginal target-closed paths whose reviewed result is the median of three routes. Keeping these
# out of the single-route subset prevents one unlucky placement from reopening a closed target.
PNR_STABILITY = ["dpd", "fft_parallel_native_x4", "ldpc_decoder_lanes_3",
                 "ldpc_decoder_z_parallel", "viterbi_decoder_soft_acs32"]

# Blocks whose reviewed engineering target is already closed and therefore strict in CI.
# Other explicit targets remain visible objectives until their architecture work lands.
TARGET_CLOSED = ["dpd", "ddc", "duc", "channelizer", "frame_sync", "resampler_farm", "ldpc_decoder",
                 "rs_decoder", "ccsds_rs_decoder",
                 "cic_decimator", "cic_interpolator", "agc", "fft_iter",
                 "viterbi_decoder", "viterbi_decoder_soft",
                 "viterbi_decoder_acs32", "viterbi_decoder_soft_acs32",
                 "cic_parallel_x2", "cic_parallel_x4",
                 "fft_folded", "fft_interleaved_x2", "fft_parallel_native_x2",
                 "fft_parallel_native_x4",
                 "goertzel_folded", "iir_biquad_folded",
                 "pfb_channelizer_folded", "pfb_channelizer_fft", "pfb_channelizer_fft_2x",
                 "ldpc_decoder_lanes_3", "ldpc_decoder_lanes_9",
                 "timing_recovery", "cfr_pipelined", "lms_equalizer_pipelined", "ddc_ip",
                 "qpsk_receiver_ip", "ldpc_decoder_z_parallel"]

# Modules whose exposed ports exceed device pins: synthesis-only (skipped by the P&R flow).
SYNTH_ONLY = ["fir", "fir_parallel_x2", "fir_parallel_x4", "mixer_parallel_x4"]
