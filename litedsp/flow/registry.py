#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""The block palette: every block the flow tool can instantiate, keyed by a stable name.

Each entry gives the class, the default construction kwargs (also the GUI's default param values),
a category, a display name, and any enumerated parameter choices. :class:`BlockSpec`s are built
lazily by reflection (see :mod:`litedsp.flow.metadata`). Blocks needing exotic constructor data
(``Replay`` samples, raw coefficient lists) are omitted; everything graph-composable is here.
"""

from litedsp.flow.metadata import reflect

from litedsp.generation.nco        import NCO
from litedsp.generation.cordic     import CORDIC
from litedsp.generation.source     import Chirp, NoiseSource
from litedsp.generation.pattern    import PatternSource
from litedsp.mixing.mixer          import Mixer
from litedsp.mixing.ddc            import DDC
from litedsp.mixing.duc            import DUC
from litedsp.mixing.channelizer    import Channelizer
from litedsp.filter.fir            import FIRFilter, FIRFilterComplex
from litedsp.filter.fir_poly       import FIRDecimator, FIRInterpolator
from litedsp.filter.cic            import CICDecimator, CICInterpolator
from litedsp.filter.halfband       import HalfbandDecimator, HalfbandInterpolator
from litedsp.filter.hilbert        import Hilbert
from litedsp.filter.iir_biquad     import IIRBiquad, IIRBiquadCascade
from litedsp.filter.dc_blocker     import DCBlocker
from litedsp.filter.moving_average import MovingAverage
from litedsp.filter.farrow         import FarrowInterpolator
from litedsp.filter.equalizer      import LMSEqualizer
from litedsp.filter.extra          import Notch, CombFilter, Allpass
from litedsp.filter.pulse_shape    import PulseShaper
from litedsp.filter.resampler      import RationalResampler
from litedsp.filter.arb_resampler  import ArbResampler
from litedsp.rate.decimator        import Decimator
from litedsp.rate.interpolator     import Interpolator
from litedsp.rate.dropper          import Downsampler, Upsampler
from litedsp.level.gain            import Gain
from litedsp.level.power           import Power
from litedsp.level.agc             import AGC
from litedsp.level.saturate        import Saturate
from litedsp.level.clipper         import Clipper
from litedsp.level.rms             import RMS
from litedsp.level.squelch         import Squelch
from litedsp.level.peak            import EnvelopeDetector
from litedsp.level.logdb           import Log2, LogPower
from litedsp.correction.dc_offset  import DCOffset
from litedsp.correction.iq_balance import IQBalance
from litedsp.correction.cfo        import Derotator
from litedsp.comm.fm_demod         import FMDemod
from litedsp.comm.am_demod         import AMDemod
from litedsp.comm.slicer           import Slicer
from litedsp.comm.mapper           import SymbolMapper
from litedsp.comm.correlator       import Correlator
from litedsp.comm.timing_recovery  import TimingRecovery
from litedsp.comm.pll              import CarrierLoop
from litedsp.comm.phase_detect     import PhaseDetect
from litedsp.comm.diff             import DifferentialEncoder, DifferentialDecoder
from litedsp.analysis.window       import Window
from litedsp.analysis.fft          import FFT
from litedsp.analysis.fft_iter     import FFTIter
from litedsp.analysis.psd          import PSD
from litedsp.analysis.welch        import WelchPSD
from litedsp.analysis.magnitude    import Magnitude
from litedsp.analysis.goertzel     import Goertzel
from litedsp.analysis.stats        import Stats
from litedsp.analysis.histogram    import Histogram
from litedsp.analysis.detect       import EnergyDetector
from litedsp.analysis.measure      import ErrorCounter
from litedsp.stream.combine        import Combine
from litedsp.stream.split          import Split
from litedsp.stream.delay          import Delay
from litedsp.stream.buffer         import SkidBuffer
from litedsp.stream.route          import ChannelMux, ChannelDemux
from litedsp.stream.capture        import Capture
from litedsp.stream.ops            import Conjugate, SwapIQ, Negate
from litedsp.stream.fifo           import StreamFIFO
from litedsp.stream.adapt          import IQPack, IQUnpack, IQClockDomainCrossing
from litedsp.stream.csr_io         import CSRSource, CSRSink, NullSink
from litedsp.stream.framing        import StreamFramer, StreamDeframer

_METHOD  = {"method": ["cic", "fir"]}
_WINDOW  = {"window": ["hann", "hamming", "blackman", "rect"]}

# (key, class, kwargs, category, display_name, choices) -- kwargs also seed the GUI defaults.
ENTRIES = [
    # generation -----------------------------------------------------------------------------------
    ("nco",            NCO,            {},                              "generation", "NCO (DDS)",          None),
    ("cordic_rot",     CORDIC,         {"mode": "rotation"},            "generation", "CORDIC (rotate)",   {"mode": ["rotation", "vectoring"]}),
    ("cordic_vec",     CORDIC,         {"mode": "vectoring"},           "generation", "CORDIC (vector)",   {"mode": ["rotation", "vectoring"]}),
    ("chirp",          Chirp,          {},                              "generation", "Chirp (LFM)",       None),
    ("noise_source",   NoiseSource,    {},                              "generation", "Noise (AWGN)",      None),
    ("pattern_source", PatternSource,  {},                              "generation", "Pattern source",    None),
    # mixing ---------------------------------------------------------------------------------------
    ("mixer",          Mixer,          {},                              "mixing", "Mixer (complex)",       None),
    ("ddc",            DDC,            {"decimation": 8},               "mixing", "DDC",                   _METHOD),
    ("duc",            DUC,            {"interpolation": 8},            "mixing", "DUC",                   _METHOD),
    ("channelizer",    Channelizer,    {"n_channels": 4, "decimation": 4}, "mixing", "Channelizer",       _METHOD),
    # filter ---------------------------------------------------------------------------------------
    ("fir_real",       FIRFilter,         {"n_taps": 32},               "filter", "FIR (real)",           None),
    ("fir_complex",    FIRFilterComplex,  {"n_taps": 32},               "filter", "FIR (complex)",        None),
    ("fir_decimator",  FIRDecimator,      {"n_taps": 32, "R": 8},       "filter", "FIR decimator",        None),
    ("fir_interpolator", FIRInterpolator, {"n_taps": 32, "L": 8},       "filter", "FIR interpolator",     None),
    ("cic_decimator",  CICDecimator,      {"R": 8, "N": 3},             "filter", "CIC decimator",        None),
    ("cic_interpolator", CICInterpolator, {"R": 8, "N": 3},             "filter", "CIC interpolator",     None),
    ("halfband_dec",   HalfbandDecimator, {},                           "filter", "Halfband decimator",   None),
    ("halfband_int",   HalfbandInterpolator, {},                        "filter", "Halfband interpolator",None),
    ("hilbert",        Hilbert,           {},                           "filter", "Hilbert",              None),
    ("iir_biquad",     IIRBiquad,         {},                           "filter", "IIR biquad",           None),
    ("dc_blocker",     DCBlocker,         {},                           "filter", "DC blocker",           None),
    ("moving_average", MovingAverage,     {},                           "filter", "Moving average",       None),
    ("farrow",         FarrowInterpolator,{},                           "filter", "Farrow interpolator",  None),
    ("equalizer",      LMSEqualizer,      {"n_taps": 7},                "filter", "LMS equalizer",        None),
    ("notch",          Notch,             {},                           "filter", "Notch",                None),
    ("comb_filter",    CombFilter,        {},                           "filter", "Comb filter",          None),
    ("allpass",        Allpass,           {},                           "filter", "Allpass",              None),
    ("pulse_shaper",   PulseShaper,       {},                           "filter", "Pulse shaper (RRC)",   None),
    ("rational_resampler", RationalResampler, {"L": 3, "M": 2},         "filter", "Rational resampler",   None),
    ("arb_resampler",  ArbResampler,      {},                           "filter", "Arbitrary resampler",  None),
    # rate -----------------------------------------------------------------------------------------
    ("decimator",      Decimator,         {"factor": 8},                "rate", "Decimator",              _METHOD),
    ("interpolator",   Interpolator,      {"factor": 8},                "rate", "Interpolator",           _METHOD),
    ("downsampler",    Downsampler,       {},                           "rate", "Downsampler",            None),
    ("upsampler",      Upsampler,         {},                           "rate", "Upsampler",              None),
    # level ----------------------------------------------------------------------------------------
    ("gain",           Gain,              {},                           "level", "Gain",                  None),
    ("power",          Power,             {},                           "level", "Power meter",           None),
    ("agc",            AGC,               {},                           "level", "AGC",                   None),
    ("saturate",       Saturate,          {},                           "level", "Saturate",             None),
    ("clipper",        Clipper,           {},                           "level", "Clipper",              None),
    ("rms",            RMS,               {},                           "level", "RMS",                   None),
    ("squelch",        Squelch,           {},                           "level", "Squelch",              None),
    ("envelope",       EnvelopeDetector,  {},                           "level", "Envelope detector",     None),
    ("log2",           Log2,              {},                           "level", "Log2",                  None),
    ("log_power",      LogPower,          {},                           "level", "Log power (dB)",        None),
    # correction -----------------------------------------------------------------------------------
    ("dc_offset",      DCOffset,          {},                           "correction", "DC offset",        None),
    ("iq_balance",     IQBalance,         {},                           "correction", "I/Q balance",      None),
    ("derotator",      Derotator,         {},                           "correction", "Derotator (CFO)",  None),
    # comm -----------------------------------------------------------------------------------------
    ("fm_demod",       FMDemod,           {},                           "comm", "FM demod",               None),
    ("am_demod",       AMDemod,           {},                           "comm", "AM demod",               None),
    ("slicer",         Slicer,            {},                           "comm", "Slicer",                 None),
    ("symbol_mapper",  SymbolMapper,      {},                           "comm", "Symbol mapper",          None),
    ("correlator",     Correlator,        {"sequence": [1, 1, 1, -1, -1, 1, -1]}, "comm", "Correlator",   None),
    ("timing_recovery",TimingRecovery,    {},                           "comm", "Timing recovery (M&M)",  None),
    ("carrier_loop",   CarrierLoop,       {},                           "comm", "Carrier loop (PLL)",     None),
    ("phase_detect",   PhaseDetect,       {},                           "comm", "Phase detector",         None),
    ("diff_encoder",   DifferentialEncoder, {},                         "comm", "Differential encoder",   None),
    ("diff_decoder",   DifferentialDecoder, {},                         "comm", "Differential decoder",   None),
    # analysis -------------------------------------------------------------------------------------
    ("window",         Window,            {"n": 64},                    "analysis", "Window",             _WINDOW),
    ("fft",            FFT,               {"N": 64},                    "analysis", "FFT (SDF)",          None),
    ("fft_iter",       FFTIter,           {"N": 64},                    "analysis", "FFT (iterative)",    None),
    ("psd",            PSD,               {"N": 64, "latency": 63},     "analysis", "PSD",                None),
    ("welch",          WelchPSD,          {"N": 64},                    "analysis", "Welch PSD",          _WINDOW),
    ("magnitude",      Magnitude,         {},                           "analysis", "Magnitude (approx)", {"method": ["approx", "cordic"]}),
    ("magnitude_cordic", Magnitude,       {"method": "cordic"},         "analysis", "Magnitude (CORDIC)", {"method": ["approx", "cordic"]}),
    ("goertzel",       Goertzel,          {"N": 64, "k": 8},            "analysis", "Goertzel",           None),
    ("stats",          Stats,             {},                           "analysis", "Stats",              None),
    ("histogram",      Histogram,         {},                           "analysis", "Histogram",          None),
    ("energy_detector",EnergyDetector,    {},                           "analysis", "Energy detector",    None),
    ("error_counter",  ErrorCounter,      {},                           "analysis", "Error counter",      None),
    # stream ---------------------------------------------------------------------------------------
    ("combine",        Combine,           {"n_channels": 2},            "stream", "Combine (sum)",        None),
    ("split",          Split,             {"n": 2},                     "stream", "Split (fan-out)",      None),
    ("delay",          Delay,             {"depth": 1},                 "stream", "Delay",                None),
    ("skid_buffer",    SkidBuffer,        {},                           "stream", "Skid buffer",          None),
    ("channel_mux",    ChannelMux,        {"n": 2},                     "stream", "Channel mux",          None),
    ("channel_demux",  ChannelDemux,      {"n": 2},                     "stream", "Channel demux",        None),
    ("capture",        Capture,           {"depth": 256},               "stream", "Capture (scope)",      None),
    ("conjugate",      Conjugate,         {},                           "stream", "Conjugate",            None),
    ("swap_iq",        SwapIQ,            {},                           "stream", "Swap I/Q",             None),
    ("negate",         Negate,            {},                           "stream", "Negate",               None),
    ("stream_fifo",    StreamFIFO,        {},                           "stream", "Stream FIFO",          None),
    ("iq_pack",        IQPack,            {},                           "stream", "I/Q pack",             None),
    ("iq_unpack",      IQUnpack,          {},                           "stream", "I/Q unpack",           None),
    ("cdc",            IQClockDomainCrossing, {},                       "stream", "Clock-domain crossing",None),
    ("csr_source",     CSRSource,         {},                           "stream", "CSR source",           None),
    ("csr_sink",       CSRSink,           {},                           "stream", "CSR sink",             None),
    ("null_sink",      NullSink,          {},                           "stream", "Null sink",            None),
    ("framer",         StreamFramer,      {},                           "stream", "Framer",               None),
    ("deframer",       StreamDeframer,    {},                           "stream", "Deframer",             None),
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
