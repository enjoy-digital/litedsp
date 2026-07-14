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
from litedsp.level.gain            import LiteDSPGain
from litedsp.level.power           import LiteDSPPower
from litedsp.level.agc             import LiteDSPAGC
from litedsp.level.saturate        import LiteDSPSaturate
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
from litedsp.comm.viterbi          import LiteDSPViterbiDecoder
from litedsp.comm.puncture         import LiteDSPPuncturer, LiteDSPDepuncturer, PUNCTURE_3_4
from litedsp.comm.ofdm             import LiteDSPCPInsert, LiteDSPCPRemove
from litedsp.analysis.window       import LiteDSPWindow
from litedsp.analysis.fft          import LiteDSPFFT
from litedsp.analysis.fft_iter     import LiteDSPFFTIter
from litedsp.analysis.psd          import LiteDSPPSD
from litedsp.analysis.welch        import LiteDSPWelchPSD
from litedsp.analysis.magnitude    import LiteDSPMagnitude
from litedsp.analysis.goertzel     import LiteDSPGoertzel
from litedsp.analysis.stats        import LiteDSPStats
from litedsp.analysis.histogram    import LiteDSPHistogram
from litedsp.analysis.detect       import LiteDSPEnergyDetector
from litedsp.analysis.measure      import LiteDSPErrorCounter
from litedsp.stream.combine        import LiteDSPCombine
from litedsp.stream.split          import LiteDSPSplit
from litedsp.stream.delay          import LiteDSPDelay
from litedsp.stream.buffer         import LiteDSPSkidBuffer
from litedsp.stream.route          import LiteDSPChannelMux, LiteDSPChannelDemux
from litedsp.stream.capture        import LiteDSPCapture
from litedsp.stream.ops            import LiteDSPConjugate, LiteDSPSwapIQ, LiteDSPNegate
from litedsp.stream.fifo           import LiteDSPStreamFIFO
from litedsp.stream.adapt          import LiteDSPIQPack, LiteDSPIQUnpack, LiteDSPIQClockDomainCrossing
from litedsp.stream.csr_io         import LiteDSPCSRSource, LiteDSPCSRSink, LiteDSPNullSink
from litedsp.stream.framing        import LiteDSPStreamFramer, LiteDSPStreamDeframer

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
    ("duc",                LiteDSPDUC,                   {"interpolation": 8},                   "mixing",     "DUC",                   _METHOD),
    ("channelizer",        LiteDSPChannelizer,           {"n_channels": 4, "decimation": 4},     "mixing",     "Channelizer",           _METHOD),
    ("pfb_channelizer",    LiteDSPPFBChannelizer,        {"n_channels": 4, "taps_per_channel": 8}, "mixing",   "PFB channelizer",       None),
    # filter ---------------------------------------------------------------------------------------
    ("fir_real",           LiteDSPFIRFilter,             {"n_taps": 32},                         "filter",     "FIR (real)",            None),
    ("fir_complex",        LiteDSPFIRFilterComplex,      {"n_taps": 32},                         "filter",     "FIR (complex)",         None),
    ("fir_decimator",      LiteDSPFIRDecimator,          {"n_taps": 32, "decimation": 8},                 "filter",     "FIR decimator",         None),
    ("fir_interpolator",   LiteDSPFIRInterpolator,       {"n_taps": 32, "interpolation": 8},                 "filter",     "FIR interpolator",      None),
    ("cic_decimator",      LiteDSPCICDecimator,          {"decimation": 8, "n_stages": 3},                       "filter",     "CIC decimator",         None),
    ("cic_interpolator",   LiteDSPCICInterpolator,       {"interpolation": 8, "n_stages": 3},                       "filter",     "CIC interpolator",      None),
    ("halfband_dec",       LiteDSPHalfbandDecimator,     {},                                     "filter",     "Halfband decimator",    None),
    ("halfband_int",       LiteDSPHalfbandInterpolator,  {},                                     "filter",     "Halfband interpolator", None),
    ("hilbert",            LiteDSPHilbert,               {},                                     "filter",     "Hilbert",               None),
    ("iir_biquad",         LiteDSPIIRBiquad,             {},                                     "filter",     "IIR biquad",            None),
    ("dc_blocker",         LiteDSPDCBlocker,             {},                                     "filter",     "DC blocker",            None),
    ("moving_average",     LiteDSPMovingAverage,         {},                                     "filter",     "Moving average",        None),
    ("farrow",             LiteDSPFarrowInterpolator,    {},                                     "filter",     "Farrow interpolator",   None),
    ("equalizer",          LiteDSPLMSEqualizer,          {"n_taps": 7},                          "filter",     "LMS equalizer",         None),
    ("notch",              LiteDSPNotch,                 {},                                     "filter",     "Notch",                 None),
    ("comb_filter",        LiteDSPCombFilter,            {},                                     "filter",     "Comb filter",           None),
    ("allpass",            LiteDSPAllpass,               {},                                     "filter",     "Allpass",               None),
    ("pulse_shaper",       LiteDSPPulseShaper,           {},                                     "filter",     "Pulse shaper (RRC)",    None),
    ("rational_resampler", LiteDSPRationalResampler,     {"interpolation": 3, "decimation": 2},                       "filter",     "Rational resampler",    None),
    ("arb_resampler",      LiteDSPArbResampler,          {},                                     "filter",     "Arbitrary resampler",   None),
    # rate -----------------------------------------------------------------------------------------
    ("decimator",          LiteDSPDecimator,             {"decimation": 8},                          "rate",       "Decimator",             _METHOD),
    ("interpolator",       LiteDSPInterpolator,          {"interpolation": 8},                          "rate",       "Interpolator",          _METHOD),
    ("downsampler",        LiteDSPDownsampler,           {},                                     "rate",       "Downsampler",           None),
    ("upsampler",          LiteDSPUpsampler,             {},                                     "rate",       "Upsampler",             None),
    # level ----------------------------------------------------------------------------------------
    ("gain",               LiteDSPGain,                  {},                                     "level",      "Gain",                  None),
    ("power",              LiteDSPPower,                 {},                                     "level",      "Power meter",           None),
    ("agc",                LiteDSPAGC,                   {},                                     "level",      "AGC",                   None),
    ("saturate",           LiteDSPSaturate,              {},                                     "level",      "Saturate",              None),
    ("clipper",            LiteDSPClipper,               {},                                     "level",      "Clipper",               None),
    ("rms",                LiteDSPRMS,                   {},                                     "level",      "RMS",                   None),
    ("squelch",            LiteDSPSquelch,               {},                                     "level",      "Squelch",               None),
    ("envelope",           LiteDSPEnvelopeDetector,      {},                                     "level",      "Envelope detector",     None),
    ("log2",               LiteDSPLog2,                  {},                                     "level",      "Log2",                  None),
    ("log_power",          LiteDSPLogPower,              {},                                     "level",      "Log power (dB)",        None),
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
    ("frame_sync",         LiteDSPFrameSync,             {"sequence": [1, 1, 1, -1, -1, 1, -1]}, "comm",       "Frame sync (preamble)", None),
    ("timing_recovery",    LiteDSPTimingRecovery,        {},                                     "comm",       "Timing recovery (M&M)", None),
    ("carrier_loop",       LiteDSPCarrierLoop,           {},                                     "comm",       "Carrier loop (PLL)",    None),
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
    ("cp_insert",          LiteDSPCPInsert,              {"fft_size": 64, "cp_len": 16},         "comm",       "OFDM CP insert",        None),
    ("cp_remove",          LiteDSPCPRemove,              {"fft_size": 64, "cp_len": 16},         "comm",       "OFDM CP remove",        None),
    # analysis -------------------------------------------------------------------------------------
    ("window",             LiteDSPWindow,                {"n": 64},                              "analysis",   "Window",                _WINDOW),
    ("fft",                LiteDSPFFT,                   {"N": 64},                              "analysis",   "FFT (SDF)",             {"scaling": ["scaled", "bfp"]}),
    ("fft_iter",           LiteDSPFFTIter,               {"N": 64},                              "analysis",   "FFT (iterative)",       None),
    ("psd",                LiteDSPPSD,                   {"N": 64},               "analysis",   "PSD",                   None),
    ("welch",              LiteDSPWelchPSD,              {"N": 64},                              "analysis",   "Welch PSD",             _WINDOW),
    ("magnitude",          LiteDSPMagnitude,             {},                                     "analysis",   "Magnitude (approx)",    {"method": ["approx", "cordic"]}),
    ("magnitude_cordic",   LiteDSPMagnitude,             {"method": "cordic"},                   "analysis",   "Magnitude (CORDIC)",    {"method": ["approx", "cordic"]}),
    ("goertzel",           LiteDSPGoertzel,              {"N": 64, "k": 8},                      "analysis",   "Goertzel",              None),
    ("stats",              LiteDSPStats,                 {},                                     "analysis",   "Stats",                 None),
    ("histogram",          LiteDSPHistogram,             {},                                     "analysis",   "Histogram",             None),
    ("energy_detector",    LiteDSPEnergyDetector,        {},                                     "analysis",   "Energy detector",       None),
    ("error_counter",      LiteDSPErrorCounter,          {},                                     "analysis",   "Error counter",         None),
    # stream ---------------------------------------------------------------------------------------
    ("combine",            LiteDSPCombine,               {"n_channels": 2},                      "stream",     "Combine (sum)",         None),
    ("split",              LiteDSPSplit,                 {"n": 2},                               "stream",     "Split (fan-out)",       None),
    ("delay",              LiteDSPDelay,                 {"depth": 1},                           "stream",     "Delay",                 None),
    ("skid_buffer",        LiteDSPSkidBuffer,            {},                                     "stream",     "Skid buffer",           None),
    ("channel_mux",        LiteDSPChannelMux,            {"n": 2},                               "stream",     "Channel mux",           None),
    ("channel_demux",      LiteDSPChannelDemux,          {"n": 2},                               "stream",     "Channel demux",         None),
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
