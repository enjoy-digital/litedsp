#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""The block palette: every block the flow tool can instantiate, keyed by a stable name.

Each entry gives the class, the default construction kwargs (also the GUI's default param values),
a category, a display name, and any enumerated parameter choices. :class:`BlockSpec`s are built
lazily by reflection (see :mod:`litedsp.flow.metadata`). Blocks needing exotic constructor data
(``LiteDSPReplay`` samples, raw coefficient lists) are omitted; everything graph-composable is here.
"""

from litedsp.flow.metadata import reflect

from litedsp.generation.nco        import LiteDSPNCO
from litedsp.generation.cordic     import LiteDSPCORDIC
from litedsp.generation.source     import LiteDSPChirp, LiteDSPNoiseSource
from litedsp.generation.pattern    import LiteDSPPatternSource
from litedsp.mixing.mixer          import LiteDSPMixer
from litedsp.mixing.ddc            import LiteDSPDDC
from litedsp.mixing.duc            import LiteDSPDUC
from litedsp.mixing.channelizer    import LiteDSPChannelizer
from litedsp.mixing.pfb_channelizer import LiteDSPPFBChannelizer
from litedsp.filter.fir            import LiteDSPFIRFilter, LiteDSPFIRFilterComplex
from litedsp.filter.fir_poly       import LiteDSPFIRDecimator, LiteDSPFIRInterpolator
from litedsp.filter.cic            import LiteDSPCICDecimator, LiteDSPCICInterpolator
from litedsp.filter.halfband       import LiteDSPHalfbandDecimator, LiteDSPHalfbandInterpolator
from litedsp.filter.hilbert        import LiteDSPHilbert
from litedsp.filter.bitstream      import LiteDSPBitstreamDecimator
from litedsp.filter.iir_biquad     import LiteDSPIIRBiquad, LiteDSPIIRBiquadCascade
from litedsp.filter.dc_blocker     import LiteDSPDCBlocker
from litedsp.filter.moving_average import LiteDSPMovingAverage
from litedsp.filter.farrow         import LiteDSPFarrowInterpolator
from litedsp.filter.equalizer      import LiteDSPLMSEqualizer
from litedsp.filter.extra          import LiteDSPNotch, LiteDSPCombFilter, LiteDSPAllpass
from litedsp.filter.pulse_shape    import LiteDSPPulseShaper
from litedsp.filter.resampler      import LiteDSPRationalResampler
from litedsp.filter.arb_resampler  import LiteDSPArbResampler
from litedsp.rate.decimator        import LiteDSPDecimator
from litedsp.rate.interpolator     import LiteDSPInterpolator
from litedsp.rate.dropper          import LiteDSPDownsampler, LiteDSPUpsampler
from litedsp.rate.farm             import LiteDSPResamplerFarm
from litedsp.level.dpd             import LiteDSPDPD
from litedsp.level.gain            import LiteDSPGain
from litedsp.level.power           import LiteDSPPower
from litedsp.level.agc             import LiteDSPAGC
from litedsp.level.saturate        import LiteDSPSaturate
from litedsp.level.cfr             import LiteDSPCFR
from litedsp.level.clipper         import LiteDSPClipper
from litedsp.level.rms             import LiteDSPRMS
from litedsp.level.squelch         import LiteDSPSquelch
from litedsp.level.peak            import LiteDSPEnvelopeDetector
from litedsp.level.logdb           import LiteDSPLog2, LiteDSPLogPower
from litedsp.correction.dc_offset  import LiteDSPDCOffset
from litedsp.correction.iq_balance import LiteDSPIQBalance
from litedsp.correction.cfo        import LiteDSPDerotator
from litedsp.comm.fm_demod         import LiteDSPFMDemod
from litedsp.comm.am_demod         import LiteDSPAMDemod
from litedsp.comm.slicer           import LiteDSPSlicer
from litedsp.comm.soft_demap       import LiteDSPSoftDemapper
from litedsp.comm.mapper           import LiteDSPSymbolMapper
from litedsp.comm.correlator       import LiteDSPCorrelator
from litedsp.comm.frame_sync       import LiteDSPFrameSync
from litedsp.comm.timing_recovery  import LiteDSPTimingRecovery
from litedsp.comm.pll              import LiteDSPCarrierLoop
from litedsp.comm.phase_detect     import LiteDSPPhaseDetect
from litedsp.comm.cfo_est          import LiteDSPCFOEstimator
from litedsp.comm.diff             import LiteDSPDifferentialEncoder, LiteDSPDifferentialDecoder
from litedsp.comm.coding           import LiteDSPScrambler, LiteDSPDescrambler, LiteDSPCRC, LiteDSPConvEncoder
from litedsp.comm.interleaver      import LiteDSPBlockInterleaver, LiteDSPBlockDeinterleaver
from litedsp.comm.viterbi          import LiteDSPViterbiDecoder
from litedsp.comm.puncture         import LiteDSPPuncturer, LiteDSPDepuncturer, PUNCTURE_3_4
from litedsp.comm.rs               import (
    LiteDSPRSEncoder, LiteDSPRSDecoder,
    LiteDSPCCSDSRSEncoder, LiteDSPCCSDSRSDecoder,
)
from litedsp.comm.ldpc             import LiteDSPLDPCEncoder, LiteDSPLDPCDecoder
from litedsp.comm.ldpc_parallel    import LiteDSPLDPCDecoderZParallel
from litedsp.comm.ofdm             import LiteDSPCPInsert, LiteDSPCPRemove
from litedsp.comm.ofdm_eq          import LiteDSPOFDMEqualizer
from litedsp.analysis.window       import LiteDSPWindow
from litedsp.analysis.fft          import LiteDSPFFT
from litedsp.analysis.fft_iter     import LiteDSPFFTIter
from litedsp.analysis.fft_parallel import LiteDSPParallelFFT
from litedsp.analysis.psd          import LiteDSPPSD
from litedsp.analysis.welch        import LiteDSPWelchPSD
from litedsp.analysis.magnitude    import LiteDSPMagnitude
from litedsp.analysis.goertzel     import LiteDSPGoertzel
from litedsp.analysis.stats        import LiteDSPStats
from litedsp.analysis.histogram    import LiteDSPHistogram
from litedsp.analysis.detect       import LiteDSPEnergyDetector
from litedsp.analysis.measure      import LiteDSPErrorCounter
from litedsp.analysis.reorder      import LiteDSPBitReverse
from litedsp.stream.combine        import LiteDSPCombine
from litedsp.stream.split          import LiteDSPSplit
from litedsp.stream.delay          import LiteDSPDelay
from litedsp.stream.buffer         import LiteDSPSkidBuffer
from litedsp.stream.route          import LiteDSPChannelMux, LiteDSPChannelDemux, LiteDSPTDMMux, LiteDSPTDMDemux
from litedsp.stream.capture        import LiteDSPCapture
from litedsp.stream.ops            import LiteDSPConjugate, LiteDSPSwapIQ, LiteDSPNegate
from litedsp.stream.fifo           import LiteDSPStreamFIFO
from litedsp.stream.adapt          import LiteDSPIQPack, LiteDSPIQUnpack, LiteDSPIQClockDomainCrossing
from litedsp.stream.csr_io         import LiteDSPCSRSource, LiteDSPCSRSink, LiteDSPNullSink
from litedsp.stream.framing        import LiteDSPStreamFramer, LiteDSPStreamDeframer
from litedsp.stream.timestamp      import LiteDSPTimestamper, LiteDSPTimeUntagger
from litedsp.motor.transforms      import (LiteDSPClarke, LiteDSPInverseClarke, LiteDSPSinCos,
    LiteDSPAngleRamp, LiteDSPPark, LiteDSPInversePark)
from litedsp.motor.pi              import LiteDSPPIController, LiteDSPDQController
from litedsp.motor.limiter         import LiteDSPSlewLimiter
from litedsp.motor.svpwm           import LiteDSPSVPWM
from litedsp.motor.pwm             import LiteDSPPWM
from litedsp.motor.sense           import LiteDSPSigmaDeltaFilter, LiteDSPOvercurrentTrip
from litedsp.motor.encoder         import LiteDSPQuadratureDecoder, LiteDSPHallDecoder
from litedsp.motor.observer        import LiteDSPAngleTracker, LiteDSPSMObserver
from litedsp.motor.resolver        import LiteDSPResolverDigital
from litedsp.motor.foc             import LiteDSPFOC
from litedsp.audio.level           import LiteDSPVolume, LiteDSPStereoMatrix
from litedsp.audio.dither          import LiteDSPDither
from litedsp.audio.eq              import LiteDSPAudioEQ
from litedsp.level.logdb           import LiteDSPExp2
from litedsp.audio.dynamics        import LiteDSPCompressor
from litedsp.audio.effects         import LiteDSPLFO, LiteDSPDelayLine, LiteDSPWetDryMix, LiteDSPReverb
from litedsp.audio.meter           import LiteDSPPeakMeter, LiteDSPLoudness
from litedsp.audio.pdm             import LiteDSPSigmaDeltaModulator, LiteDSPSigmaDeltaDAC, LiteDSPPDMReceiver
from litedsp.audio.i2s             import LiteDSPI2SReceiver, LiteDSPI2STransmitter
from litedsp.comm.fm_mod           import LiteDSPFrequencyModulator, LiteDSPPhaseModulator
from litedsp.radar.timing          import LiteDSPRangeGate, LiteDSPPulseGenerator
from litedsp.radar.compress        import LiteDSPPulseCompressor
from litedsp.radar.mti             import LiteDSPMTICanceller
from litedsp.radar.corner_turn     import LiteDSPCornerTurn
from litedsp.radar.doppler         import LiteDSPDopplerProcessor
from litedsp.radar.cfar            import LiteDSPCACFAR, LiteDSPOSCFAR
from litedsp.radar.clutter         import LiteDSPClutterMap
from litedsp.radar.cfar_2d         import LiteDSPCFAR2D
from litedsp.radar.detect          import LiteDSPPeakExtractor, LiteDSPTargetList
from litedsp.radar.track           import LiteDSPAlphaBetaTracker
from litedsp.radar.kalman          import LiteDSPKalmanTracker
from litedsp.radar.beamform        import LiteDSPBeamformer, LiteDSPMonopulse
from litedsp.radar.sonar           import LiteDSPTVG
from litedsp.image.pattern         import LiteDSPPixelPattern
from litedsp.image.adapt           import LiteDSPPixelPack, LiteDSPPixelUnpack
from litedsp.image.video           import LiteDSPPixelFromVideo, LiteDSPPixelToVideo
from litedsp.image.linebuffer      import LiteDSPLineBuffer
from litedsp.image.stream          import LiteDSPPixelFIFO
from litedsp.image.kernel          import LiteDSPKernel2D
from litedsp.image.design          import kernel_preset
from litedsp.image.edge            import LiteDSPSobel
from litedsp.image.rank            import LiteDSPRankFilter
from litedsp.image.point           import LiteDSPThreshold, LiteDSPPixelGain
from litedsp.image.lut             import LiteDSPPixelLUT
from litedsp.image.color           import LiteDSPColorMatrix
from litedsp.image.debayer         import LiteDSPDebayer
from litedsp.image.scale           import LiteDSPDownscaler, LiteDSPCrop
from litedsp.image.design          import color_preset
from litedsp.image.stats           import LiteDSPPixelStats
from litedsp.image.histogram       import LiteDSPPixelHistogram
from litedsp.image.blend           import LiteDSPAlphaBlend
from litedsp.image.overlay         import LiteDSPBoxOverlay

_METHOD  = {"method": ["cic", "fir"]}
_WINDOW  = {"window": ["hann", "hamming", "blackman", "rect"]}

# (key, class, kwargs, category, display_name, choices) -- kwargs also seed the GUI defaults.
ENTRIES = [
    # generation -----------------------------------------------------------------------------------
    ("nco",                LiteDSPNCO,                   {},                                     "generation", "NCO (DDS)",             None),
    ("cordic_rot",         LiteDSPCORDIC,                {"mode": "rotation"},                   "generation", "CORDIC (rotate)",       {"mode": ["rotation", "vectoring"]}),
    ("cordic_vec",         LiteDSPCORDIC,                {"mode": "vectoring"},                  "generation", "CORDIC (vector)",       {"mode": ["rotation", "vectoring"]}),
    ("chirp",              LiteDSPChirp,                 {},                                     "generation", "Chirp (LFM)",           None),
    ("noise_source",       LiteDSPNoiseSource,           {},                                     "generation", "Noise (AWGN)",          None),
    ("pattern_source",     LiteDSPPatternSource,         {},                                     "generation", "Pattern source",        None),
    # mixing ---------------------------------------------------------------------------------------
    ("mixer",              LiteDSPMixer,                 {},                                     "mixing",     "Mixer (complex)",       None),
    ("ddc",                LiteDSPDDC,                   {"decimation": 8},                      "mixing",     "DDC",                   _METHOD),
    ("duc",                LiteDSPDUC,                   {"interpolation": 8},                   "mixing",     "DUC",                   {"method": ["cic", "fir"], "fir_architecture": ["classic", "pipelined"]}),
    ("channelizer",        LiteDSPChannelizer,           {"n_channels": 4, "decimation": 4},     "mixing",     "Channelizer",           {"method": ["cic", "fir"], "fir_architecture": ["classic", "pipelined"]}),
    ("pfb_channelizer",    LiteDSPPFBChannelizer,        {"n_channels": 4, "taps_per_channel": 8, "architecture": "auto"}, "mixing", "PFB channelizer (scalable)", {"architecture": ["auto", "classic", "folded", "fft"]}),
    # filter ---------------------------------------------------------------------------------------
    ("bitstream_decimator", LiteDSPBitstreamDecimator,   {},                                     "filter",     "Bitstream (sigma-delta/PDM) decimator", None),
    ("fir_real",           LiteDSPFIRFilter,             {"n_taps": 32},                         "filter",     "FIR (real)",            {"architecture": ["classic", "pipelined", "mac"]}),
    ("fir_complex",        LiteDSPFIRFilterComplex,      {"n_taps": 32},                         "filter",     "FIR (complex)",         {"architecture": ["classic", "pipelined", "mac"]}),
    ("fir_decimator",      LiteDSPFIRDecimator,          {"n_taps": 32, "decimation": 8},                 "filter",     "FIR decimator",         None),
    ("fir_interpolator",   LiteDSPFIRInterpolator,       {"n_taps": 32, "interpolation": 8},                 "filter",     "FIR interpolator",      {"architecture": ["classic", "pipelined"]}),
    ("cic_decimator",      LiteDSPCICDecimator,          {"decimation": 8, "n_stages": 3},                       "filter",     "CIC decimator",         None),
    ("cic_interpolator",   LiteDSPCICInterpolator,       {"interpolation": 8, "n_stages": 3},                       "filter",     "CIC interpolator",      None),
    ("halfband_dec",       LiteDSPHalfbandDecimator,     {},                                     "filter",     "Halfband decimator",    None),
    ("halfband_int",       LiteDSPHalfbandInterpolator,  {},                                     "filter",     "Halfband interpolator", None),
    ("hilbert",            LiteDSPHilbert,               {},                                     "filter",     "Hilbert",               None),
    ("iir_biquad",         LiteDSPIIRBiquad,             {},                                     "filter",     "IIR biquad",            {"architecture": ["classic", "folded"]}),
    ("dc_blocker",         LiteDSPDCBlocker,             {},                                     "filter",     "DC blocker",            None),
    ("dc_blocker_real",    LiteDSPDCBlocker,             {"iq": False, "data_width": 24, "precision_bits": 8}, "filter", "DC blocker (mono)", None),
    ("moving_average",     LiteDSPMovingAverage,         {},                                     "filter",     "Moving average",        None),
    ("farrow",             LiteDSPFarrowInterpolator,    {},                                     "filter",     "Farrow interpolator",   None),
    ("equalizer",          LiteDSPLMSEqualizer,          {"n_taps": 7},                          "filter",     "LMS equalizer",         {"architecture": ["classic", "pipelined"]}),
    ("notch",              LiteDSPNotch,                 {},                                     "filter",     "Notch",                 None),
    ("comb_filter",        LiteDSPCombFilter,            {},                                     "filter",     "Comb filter",           None),
    ("allpass",            LiteDSPAllpass,               {},                                     "filter",     "Allpass",               None),
    ("pulse_shaper",       LiteDSPPulseShaper,           {},                                     "filter",     "Pulse shaper (RRC)",    None),
    ("rational_resampler", LiteDSPRationalResampler,     {"interpolation": 3, "decimation": 2},                       "filter",     "Rational resampler",    None),
    ("arb_resampler",      LiteDSPArbResampler,          {},                                     "filter",     "Arbitrary resampler",   None),
    # rate -----------------------------------------------------------------------------------------
    ("decimator",          LiteDSPDecimator,             {"decimation": 8},                          "rate",       "Decimator",             _METHOD),
    ("interpolator",       LiteDSPInterpolator,          {"interpolation": 8},                          "rate",       "Interpolator",          {"method": ["cic", "fir"], "fir_architecture": ["classic", "pipelined"]}),
    ("downsampler",        LiteDSPDownsampler,           {},                                     "rate",       "Downsampler",           None),
    ("upsampler",          LiteDSPUpsampler,             {},                                     "rate",       "Upsampler",             None),
    ("resampler_farm",     LiteDSPResamplerFarm,         {"n_channels": 4, "n_taps": 32, "decimation": 8}, "rate", "Resampler farm",      {"architecture": ["classic", "pipelined"]}),
    # level ----------------------------------------------------------------------------------------
    ("gain",               LiteDSPGain,                  {},                                     "level",      "Gain",                  None),
    ("power",              LiteDSPPower,                 {},                                     "level",      "Power meter",           None),
    ("agc",                LiteDSPAGC,                   {},                                     "level",      "AGC",                   None),
    ("dpd",                LiteDSPDPD,                   {},                                     "level",      "DPD actuator",          None),
    ("saturate",           LiteDSPSaturate,              {},                                     "level",      "Saturate",              None),
    ("cfr",                LiteDSPCFR,                   {},                                     "level",      "CFR (peak cancellation)", {"architecture": ["classic", "pipelined"]}),
    ("clipper",            LiteDSPClipper,               {},                                     "level",      "Clipper",               None),
    ("rms",                LiteDSPRMS,                   {},                                     "level",      "RMS",                   None),
    ("squelch",            LiteDSPSquelch,               {},                                     "level",      "Squelch",               None),
    ("envelope",           LiteDSPEnvelopeDetector,      {},                                     "level",      "Envelope detector",     None),
    ("log2",               LiteDSPLog2,                  {},                                     "level",      "Log2",                  None),
    ("log_power",          LiteDSPLogPower,              {},                                     "level",      "Log power (dB)",        None),
    ("exp2",               LiteDSPExp2,                  {},                                     "level",      "Exp2 (antilog)",        None),
    # correction -----------------------------------------------------------------------------------
    ("dc_offset",          LiteDSPDCOffset,              {},                                     "correction", "DC offset",             None),
    ("iq_balance",         LiteDSPIQBalance,             {},                                     "correction", "I/Q balance",           None),
    ("derotator",          LiteDSPDerotator,             {},                                     "correction", "Derotator (CFO)",       None),
    # comm -----------------------------------------------------------------------------------------
    ("fm_demod",           LiteDSPFMDemod,               {},                                     "comm",       "FM demod",              None),
    ("am_demod",           LiteDSPAMDemod,               {},                                     "comm",       "AM demod",              None),
    ("slicer",             LiteDSPSlicer,                {},                                     "comm",       "Slicer",                None),
    ("soft_demapper",      LiteDSPSoftDemapper,          {},                                     "comm",       "Soft demapper (LLR)",   None),
    ("symbol_mapper",      LiteDSPSymbolMapper,          {},                                     "comm",       "Symbol mapper",         None),
    ("correlator",         LiteDSPCorrelator,            {"sequence": [1, 1, 1, -1, -1, 1, -1]}, "comm",       "Correlator",            None),
    ("frame_sync",         LiteDSPFrameSync,             {"sequence": [1, 1, 1, -1, -1, 1, -1]}, "comm",       "Frame sync (preamble)", {"architecture": ["classic", "pipelined"]}),
    ("timing_recovery",    LiteDSPTimingRecovery,        {},                                     "comm",       "Timing recovery (M&M)", None),
    ("carrier_loop",       LiteDSPCarrierLoop,           {"detector": "pll"},                    "comm",       "Carrier loop (PLL)",    {"detector": ["pll", "bpsk", "qpsk"], "architecture": ["classic", "pipelined"]}),
    ("phase_detect",       LiteDSPPhaseDetect,           {},                                     "comm",       "Phase detector",        None),
    ("cfo_estimator",      LiteDSPCFOEstimator,          {},                                     "comm",       "CFO estimator (coarse)", None),
    ("diff_encoder",       LiteDSPDifferentialEncoder,   {},                                     "comm",       "Differential encoder",  None),
    ("diff_decoder",       LiteDSPDifferentialDecoder,   {},                                     "comm",       "Differential decoder",  None),
    ("scrambler",          LiteDSPScrambler,             {},                                     "comm",       "Scrambler (LFSR)",      None),
    ("descrambler",        LiteDSPDescrambler,           {},                                     "comm",       "Descrambler (LFSR)",    None),
    ("crc",                LiteDSPCRC,                   {},                                     "comm",       "CRC",                   None),
    ("conv_encoder",       LiteDSPConvEncoder,           {},                                     "comm",       "Convolutional encoder", None),
    ("viterbi_decoder",    LiteDSPViterbiDecoder,        {},                                     "comm",       "Viterbi decoder",       None),
    ("puncturer",          LiteDSPPuncturer,             {"pattern": PUNCTURE_3_4},              "comm",       "Puncturer",             None),
    ("depuncturer",        LiteDSPDepuncturer,           {"pattern": PUNCTURE_3_4},              "comm",       "Depuncturer (LLR)",     None),
    ("block_interleaver",  LiteDSPBlockInterleaver,      {},                                     "comm",       "Block interleaver",     None),
    ("block_deinterleaver", LiteDSPBlockDeinterleaver,   {},                                     "comm",       "Block deinterleaver",   None),
    ("rs_encoder",         LiteDSPRSEncoder,             {},                                     "comm",       "RS encoder (255,k)",    None),
    ("rs_decoder",         LiteDSPRSDecoder,             {},                                     "comm",       "RS decoder (255,k)",    {"architecture": ["classic", "pipelined"]}),
    ("ccsds_rs_encoder",   LiteDSPCCSDSRSEncoder,        {},                                     "comm",       "CCSDS RS encoder",      None),
    ("ccsds_rs_decoder",   LiteDSPCCSDSRSDecoder,        {},                                     "comm",       "CCSDS RS decoder",      {"architecture": ["classic", "pipelined"]}),
    ("ldpc_encoder",       LiteDSPLDPCEncoder,           {},                                     "comm",       "LDPC encoder (802.11n)", None),
    ("ldpc_decoder",       LiteDSPLDPCDecoder,           {},                                     "comm",       "LDPC decoder (802.11n)", None),
    ("ldpc_decoder_z_parallel", LiteDSPLDPCDecoderZParallel, {},                                  "comm",       "LDPC decoder (z-parallel)", None),
    ("cp_insert",          LiteDSPCPInsert,              {"fft_size": 64, "cp_len": 16},         "comm",       "OFDM CP insert",        None),
    ("cp_remove",          LiteDSPCPRemove,              {"fft_size": 64, "cp_len": 16},         "comm",       "OFDM CP remove",        None),
    ("ofdm_equalizer",     LiteDSPOFDMEqualizer,         {"fft_size": 64},                       "comm",       "OFDM equalizer (1-tap)", None),
    # analysis -------------------------------------------------------------------------------------
    ("window",             LiteDSPWindow,                {"n": 64},                              "analysis",   "Window",                _WINDOW),
    ("fft",                LiteDSPFFT,                   {"N": 64},                              "analysis",   "FFT (SDF)",             {"scaling": ["scaled", "bfp"], "architecture": ["classic", "folded"]}),
    ("fft_iter",           LiteDSPFFTIter,               {"N": 64},                              "analysis",   "FFT (iterative)",       None),
    ("parallel_fft",       LiteDSPParallelFFT,           {"N": 64},                              "analysis",   "FFT (parallel, P samples/clk)", {"core_architecture": ["classic", "folded"], "implementation": ["split", "native"], "n_samples": [2, 4]}),
    ("psd",                LiteDSPPSD,                   {"N": 64},               "analysis",   "PSD",                   None),
    ("welch",              LiteDSPWelchPSD,              {"N": 64},                              "analysis",   "Welch PSD",             _WINDOW),
    ("magnitude",          LiteDSPMagnitude,             {},                                     "analysis",   "Magnitude (approx)",    {"method": ["approx", "cordic"]}),
    ("magnitude_cordic",   LiteDSPMagnitude,             {"method": "cordic"},                   "analysis",   "Magnitude (CORDIC)",    {"method": ["approx", "cordic"]}),
    ("goertzel",           LiteDSPGoertzel,              {"N": 64, "k": 8},                      "analysis",   "Goertzel",              {"architecture": ["classic", "folded"]}),
    ("stats",              LiteDSPStats,                 {},                                     "analysis",   "Stats",                 None),
    ("histogram",          LiteDSPHistogram,             {},                                     "analysis",   "Histogram",             None),
    ("energy_detector",    LiteDSPEnergyDetector,        {},                                     "analysis",   "Energy detector",       None),
    ("bit_reverse",        LiteDSPBitReverse,            {"N": 64},                              "analysis",   "Bit-reverse reorder",   None),
    ("error_counter",      LiteDSPErrorCounter,          {},                                     "analysis",   "Error counter",         None),
    # stream ---------------------------------------------------------------------------------------
    ("combine",            LiteDSPCombine,               {"n_channels": 2},                      "stream",     "Combine (sum)",         None),
    ("split",              LiteDSPSplit,                 {"n": 2},                               "stream",     "Split (fan-out)",       None),
    ("delay",              LiteDSPDelay,                 {"depth": 1},                           "stream",     "Delay",                 None),
    ("skid_buffer",        LiteDSPSkidBuffer,            {},                                     "stream",     "Skid buffer",           None),
    ("channel_mux",        LiteDSPChannelMux,            {"n": 2},                               "stream",     "Channel mux",           None),
    ("channel_demux",      LiteDSPChannelDemux,          {"n": 2},                               "stream",     "Channel demux",         None),
    ("tdm_mux",            LiteDSPTDMMux,                {},                                     "stream",     "TDM mux (interleave)",  None),
    ("tdm_demux",          LiteDSPTDMDemux,              {},                                     "stream",     "TDM demux",             None),
    ("capture",            LiteDSPCapture,               {"depth": 256},                         "stream",     "Capture (scope)",       None),
    ("conjugate",          LiteDSPConjugate,             {},                                     "stream",     "Conjugate",             None),
    ("swap_iq",            LiteDSPSwapIQ,                {},                                     "stream",     "Swap I/Q",              None),
    ("negate",             LiteDSPNegate,                {},                                     "stream",     "Negate",                None),
    ("stream_fifo",        LiteDSPStreamFIFO,            {},                                     "stream",     "Stream FIFO",           None),
    ("iq_pack",            LiteDSPIQPack,                {},                                     "stream",     "I/Q pack",              None),
    ("iq_unpack",          LiteDSPIQUnpack,              {},                                     "stream",     "I/Q unpack",            None),
    ("cdc",                LiteDSPIQClockDomainCrossing, {},                                     "stream",     "Clock-domain crossing", None),
    ("csr_source",         LiteDSPCSRSource,             {},                                     "stream",     "CSR source",            None),
    ("csr_sink",           LiteDSPCSRSink,               {},                                     "stream",     "CSR sink",              None),
    ("null_sink",          LiteDSPNullSink,              {},                                     "stream",     "Null sink",             None),
    ("framer",             LiteDSPStreamFramer,          {},                                     "stream",     "Framer",                None),
    ("deframer",           LiteDSPStreamDeframer,        {},                                     "stream",     "Deframer",              None),
    # LiteDSPTimeCore is CSR-only (no stream ports), so it lives outside the palette.
    ("timestamper",        LiteDSPTimestamper,           {},                                     "stream",     "Timestamper",           None),
    ("time_untagger",      LiteDSPTimeUntagger,          {},                                     "stream",     "Time untagger",         None),
    # motor ----------------------------------------------------------------------------------------
    ("clarke",             LiteDSPClarke,                {},                                     "motor",      "Clarke (abc -> ab)",    None),
    ("inverse_clarke",     LiteDSPInverseClarke,         {},                                     "motor",      "Inverse Clarke",        None),
    ("sincos",             LiteDSPSinCos,                {},                                     "motor",      "Sin/Cos (angle)",       {"method": ["rom", "cordic"]}),
    ("angle_ramp",         LiteDSPAngleRamp,             {},                                     "motor",      "Angle ramp",            None),
    ("park",               LiteDSPPark,                  {},                                     "motor",      "Park (ab -> dq)",       {"method": ["rom", "cordic"]}),
    ("inverse_park",       LiteDSPInversePark,           {},                                     "motor",      "Inverse Park",          {"method": ["rom", "cordic"]}),
    ("pi_controller",      LiteDSPPIController,          {},                                     "motor",      "PI controller",         {"anti_windup": ["conditional", "clamp", "none"]}),
    ("dq_controller",      LiteDSPDQController,          {},                                     "motor",      "d/q current controller", {"anti_windup": ["conditional", "clamp", "none"]}),
    ("slew_limiter",       LiteDSPSlewLimiter,           {},                                     "motor",      "Slew limiter",          None),
    ("svpwm",              LiteDSPSVPWM,                 {},                                     "motor",      "SVPWM modulator",       {"injection": ["minmax", "none"]}),
    ("pwm",                LiteDSPPWM,                   {},                                     "motor",      "3-phase PWM",           None),
    ("sigma_delta_filter", LiteDSPSigmaDeltaFilter,      {},                                     "motor",      "Sigma-delta current sense", None),
    ("overcurrent_trip",   LiteDSPOvercurrentTrip,       {},                                     "motor",      "Over-current trip",     None),
    ("quadrature_decoder", LiteDSPQuadratureDecoder,     {},                                     "motor",      "Quadrature encoder",    None),
    ("hall_decoder",       LiteDSPHallDecoder,           {},                                     "motor",      "Hall sensor decoder",   None),
    ("angle_tracker",      LiteDSPAngleTracker,          {},                                     "motor",      "Angle tracker (PLL)",   None),
    ("smo_observer",       LiteDSPSMObserver,            {},                                     "motor",      "Sliding-mode observer", None),
    ("resolver",           LiteDSPResolverDigital,       {},                                     "motor",      "Resolver-to-digital",   None),
    ("foc",                LiteDSPFOC,                   {},                                     "motor",      "FOC current controller", {"anti_windup": ["conditional", "clamp", "none"]}),
    # audio ----------------------------------------------------------------------------------------
    ("volume",             LiteDSPVolume,                {},                                     "audio",      "Volume (ramped)",       None),
    ("stereo_matrix",      LiteDSPStereoMatrix,          {},                                     "audio",      "Stereo matrix (M/S, pan)", None),
    ("dither",             LiteDSPDither,                {},                                     "audio",      "Dither / requantizer",  {"shaping": ["none", "ef1", "ef2"]}),
    ("audio_eq",           LiteDSPAudioEQ,               {},                                     "audio",      "Parametric EQ",         None),
    ("compressor",         LiteDSPCompressor,            {},                                     "audio",      "Compressor",            {"preset": ["compressor", "limiter", "gate"]}),
    ("limiter",            LiteDSPCompressor,            {"preset": "limiter", "lookahead": 32}, "audio",      "Limiter (lookahead)",   {"preset": ["compressor", "limiter", "gate"]}),
    ("noise_gate",         LiteDSPCompressor,            {"preset": "gate"},                     "audio",      "Noise gate / expander", {"preset": ["compressor", "limiter", "gate"]}),
    ("lfo",                LiteDSPLFO,                   {},                                     "audio",      "LFO",                   None),
    ("delay_line",         LiteDSPDelayLine,             {},                                     "audio",      "Delay line (echo)",     None),
    ("chorus",             LiteDSPDelayLine,             {"modulation": True, "max_delay": 512}, "audio",      "Chorus / flanger",      None),
    ("wet_dry_mix",        LiteDSPWetDryMix,             {},                                     "audio",      "Wet/dry mix",           None),
    ("reverb",             LiteDSPReverb,                {},                                     "audio",      "Reverb",                None),
    ("peak_meter",         LiteDSPPeakMeter,             {},                                     "audio",      "Peak meter",            None),
    ("loudness",           LiteDSPLoudness,              {},                                     "audio",      "Loudness (BS.1770)",    None),
    ("sigma_delta_mod",    LiteDSPSigmaDeltaModulator,   {},                                     "audio",      "Sigma-delta modulator", {"order": [1, 2]}),
    ("sigma_delta_dac",    LiteDSPSigmaDeltaDAC,         {},                                     "audio",      "PDM DAC",               None),
    ("pdm_rx",             LiteDSPPDMReceiver,           {},                                     "audio",      "PDM receiver",          None),
    ("i2s_rx",             LiteDSPI2SReceiver,           {},                                     "audio",      "I2S receiver",          {"fmt": ["i2s", "left_justified", "right_justified", "tdm"], "mode": ["slave", "master"]}),
    # Radar / sonar.
    ("fm_modulator",       LiteDSPFrequencyModulator,    {},                                     "comm",       "FM modulator",          {}),
    ("pm_modulator",       LiteDSPPhaseModulator,        {},                                     "comm",       "Phase modulator",       {}),
    ("pixel_pattern",      LiteDSPPixelPattern,          {"data_width": 8, "width": 64, "height": 48}, "image", "Pixel pattern source", {"mode": ["const", "ramp", "bars", "checker", "counter", "bayer"], "n_channels": [1, 3]}),
    ("pixel_from_video",   LiteDSPPixelFromVideo,        {"data_width": 8, "width": 64, "height": 48}, "image", "Pixels from LiteX video", {}),
    ("pixel_to_video",     LiteDSPPixelToVideo,          {"data_width": 8},                      "image",      "Pixels to LiteX video", {}),
    ("line_buffer",        LiteDSPLineBuffer,            {"data_width": 8, "width": 64},         "image",      "Line buffer (window)",  {"kernel_size": [3, 5, 7], "border": ["replicate", "mirror", "zero"], "n_channels": [1, 3]}),
    ("kernel_2d", LiteDSPKernel2D, dict(data_width=8, width=64, n_channels=1, kernel_size=3, coefficients=kernel_preset("identity")[0], shift=kernel_preset("identity")[1], offset=kernel_preset("identity")[2]), "image", "2-D kernel (3x3)", {"border": ["replicate", "mirror", "zero"], "n_channels": [1, 3]}),
    ("kernel_5x5", LiteDSPKernel2D, dict(data_width=8, width=64, n_channels=1, kernel_size=5, coefficients=kernel_preset("gaussian5")[0], shift=kernel_preset("gaussian5")[1], offset=kernel_preset("gaussian5")[2]), "image", "2-D kernel (5x5)", {"border": ["replicate", "mirror", "zero"], "n_channels": [1, 3]}),
    ("gaussian_blur", LiteDSPKernel2D, dict(data_width=8, width=64, n_channels=1, kernel_size=3, coefficients=kernel_preset("gaussian3")[0], shift=kernel_preset("gaussian3")[1], offset=kernel_preset("gaussian3")[2]), "image", "Gaussian blur", {"border": ["replicate", "mirror", "zero"], "n_channels": [1, 3]}),
    ("sharpen", LiteDSPKernel2D, dict(data_width=8, width=64, n_channels=1, kernel_size=3, coefficients=kernel_preset("sharpen")[0], shift=kernel_preset("sharpen")[1], offset=kernel_preset("sharpen")[2]), "image", "Sharpen", {"border": ["replicate", "mirror", "zero"], "n_channels": [1, 3]}),
    ("laplacian", LiteDSPKernel2D, dict(data_width=8, width=64, n_channels=1, kernel_size=3, coefficients=kernel_preset("laplacian")[0], shift=kernel_preset("laplacian")[1], offset=kernel_preset("laplacian")[2]), "image", "Laplacian", {"border": ["replicate", "mirror", "zero"], "n_channels": [1, 3]}),
    ("sobel",              LiteDSPSobel,                 {"data_width": 8, "width": 64},         "image",      "Sobel edge magnitude",  {"mode": ["l1", "linf", "approx"], "border": ["replicate", "mirror", "zero"]}),
    ("rank_filter",        LiteDSPRankFilter,            {"data_width": 8, "width": 64},         "image",      "Rank filter (median)",  {"border": ["replicate", "mirror", "zero"], "n_channels": [1, 3]}),
    ("erode",              LiteDSPRankFilter,            {"data_width": 8, "width": 64, "rank": 0}, "image",   "Erosion (3x3 min)",     {"n_channels": [1, 3]}),
    ("dilate",             LiteDSPRankFilter,            {"data_width": 8, "width": 64, "rank": 8}, "image",   "Dilation (3x3 max)",    {"n_channels": [1, 3]}),
    ("threshold",          LiteDSPThreshold,             {"data_width": 8},                      "image",      "Threshold (hysteresis)", {}),
    ("pixel_gain",         LiteDSPPixelGain,             {"data_width": 8},                      "image",      "Pixel gain / offset",   {"n_channels": [1, 3]}),
    ("pixel_lut",          LiteDSPPixelLUT,              {"data_width": 8},                      "image",      "Pixel LUT",             {"n_channels": [1, 3], "shared": [True, False]}),
    ("gamma",              LiteDSPPixelLUT,              {"data_width": 8, "n_channels": 3, "gamma": 2.2}, "image", "Gamma (LUT)",      {}),
    ("color_matrix", LiteDSPColorMatrix, dict(data_width=8, n_out=3, coefficients=color_preset("identity")[0], in_offsets=color_preset("identity")[1], out_offsets=color_preset("identity")[2]), "image", "Colour matrix", {}),
    ("rgb_to_ycbcr", LiteDSPColorMatrix, dict(data_width=8, n_out=3, coefficients=color_preset("rgb_to_ycbcr_601")[0], in_offsets=color_preset("rgb_to_ycbcr_601")[1], out_offsets=color_preset("rgb_to_ycbcr_601")[2]), "image", "RGB to YCbCr (601)", {}),
    ("ycbcr_to_rgb", LiteDSPColorMatrix, dict(data_width=8, n_out=3, coefficients=color_preset("ycbcr_to_rgb_601")[0], in_offsets=color_preset("ycbcr_to_rgb_601")[1], out_offsets=color_preset("ycbcr_to_rgb_601")[2]), "image", "YCbCr to RGB (601)", {}),
    ("rgb_to_gray", LiteDSPColorMatrix, dict(data_width=8, n_out=1, coefficients=color_preset("rgb_to_gray_601")[0], in_offsets=color_preset("rgb_to_gray_601")[1], out_offsets=color_preset("rgb_to_gray_601")[2]), "image", "RGB to grey (601)", {}),
    ("debayer",            LiteDSPDebayer,               {"data_width": 8, "width": 64},         "image",      "Debayer (bilinear)",    {"pattern": ["rggb", "bggr", "grbg", "gbrg"], "border": ["mirror", "replicate", "zero"]}),
    ("downscaler",         LiteDSPDownscaler,            {"data_width": 8, "width": 64, "height": 48}, "image", "Box downscaler",        {"decimation": [2, 4, 8], "n_channels": [1, 3]}),
    ("crop",               LiteDSPCrop,                  {"data_width": 8, "roi_width": 32, "roi_height": 24}, "image", "Crop (ROI)",     {"n_channels": [1, 3]}),
    ("pixel_stats",        LiteDSPPixelStats,            {"data_width": 8},                      "image",      "Frame statistics tap",  {"zones": [1, 2, 4, 8], "n_channels": [1, 3]}),
    ("pixel_histogram",    LiteDSPPixelHistogram,        {"data_width": 8},                      "image",      "Frame histogram",       {"bins_log2": [4, 5, 6, 7, 8], "n_channels": [1, 3]}),
    ("alpha_blend",        LiteDSPAlphaBlend,            {"data_width": 8},                      "image",      "Alpha blend",           {"n_channels": [1, 3]}),
    ("mask_blend",         LiteDSPAlphaBlend,            {"data_width": 8, "with_alpha_sink": True}, "image",  "Mask blend",            {"n_channels": [1, 3]}),
    ("box_overlay",        LiteDSPBoxOverlay,            {"data_width": 8},                      "image",      "Box overlay",           {"n_channels": [1, 3]}),
    ("pixel_fifo",         LiteDSPPixelFIFO,             {"data_width": 8, "depth": 256},        "image",      "Pixel FIFO",            {"n_channels": [1, 3]}),
    ("pixel_pack",         LiteDSPPixelPack,             {"data_width": 8},                      "image",      "Pixel pack",            {"format": ["rgb888", "xrgb8888", "rgb565", "mono"]}),
    ("pixel_unpack",       LiteDSPPixelUnpack,           {"data_width": 8, "width": 64},         "image",      "Pixel unpack",          {"format": ["rgb888", "xrgb8888", "rgb565", "mono"]}),
    ("pulse_generator",    LiteDSPPulseGenerator,        {},                                     "radar",      "Pulse generator",       {}),
    ("range_gate",         LiteDSPRangeGate,             {},                                     "radar",      "Range gate (PRI timer)", None),
    ("mti",                LiteDSPMTICanceller,          {},                                     "radar",      "MTI canceller",         None),
    ("corner_turn",        LiteDSPCornerTurn,            {},                                     "radar",      "Corner turn (fast to slow time)", None),
    ("ca_cfar",            LiteDSPCACFAR,                {},                                     "radar",      "CA-CFAR detector",      {}),
    ("os_cfar",            LiteDSPOSCFAR,                {},                                     "radar",      "OS-CFAR detector",      {}),
    ("clutter_map",        LiteDSPClutterMap,            {},                                     "radar",      "Clutter map",           {}),
    ("cfar_2d",            LiteDSPCFAR2D,                {},                                     "radar",      "2-D CA-CFAR detector",  {}),
    ("peak_extractor",     LiteDSPPeakExtractor,         {},                                     "radar",      "Peak extractor",        {}),
    ("target_list",        LiteDSPTargetList,            {},                                     "radar",      "Target list",           {}),
    ("kalman_tracker",     LiteDSPKalmanTracker,         {},                                     "radar",      "Kalman tracker",        {}),
    ("beamformer",         LiteDSPBeamformer,            {},                                     "radar",      "Beamformer",            {}),
    ("monopulse",          LiteDSPMonopulse,             {},                                     "radar",      "Monopulse angle",       {}),
    ("tvg",                LiteDSPTVG,                   {},                                     "radar",      "Time-varying gain",     {}),
    ("alpha_beta_tracker", LiteDSPAlphaBetaTracker,      {},                                     "radar",      "Alpha-beta tracker",    {}),
    ("doppler",            LiteDSPDopplerProcessor,      {},                                     "radar",      "Doppler processor",     {"window": ["rect", "hann", "hamming", "blackman"], "magnitude": ["approx", "power"]}),
    ("pulse_compressor",   LiteDSPPulseCompressor,       {},                                     "radar",      "Pulse compressor (chirp matched filter)", {"window": ["rect", "hann", "hamming", "blackman"], "fir_architecture": ["classic", "pipelined", "mac"]}),
    ("i2s_tx",             LiteDSPI2STransmitter,        {},                                     "audio",      "I2S transmitter",       {"fmt": ["i2s", "left_justified", "right_justified", "tdm"], "mode": ["master", "slave"]}),
]

# Lazy registry ------------------------------------------------------------------------------------

_CACHE = None

def registry():
    """Return ``{key: BlockSpec}`` for the whole palette (built once, cached)."""
    global _CACHE
    if _CACHE is None:
        _CACHE = {}
        for key, cls, kwargs, category, display, choices in ENTRIES:
            _CACHE[key] = reflect(key, cls, kwargs, category=category,
                display_name=display, choices=choices)
    return _CACHE

def get(key):
    try:
        return registry()[key]
    except KeyError:
        raise KeyError(f"unknown block type '{key}' (known: {', '.join(sorted(registry()))})")

def keys():
    return sorted(registry())

def by_category():
    out = {}
    for spec in registry().values():
        out.setdefault(spec.category, []).append(spec)
    return out
