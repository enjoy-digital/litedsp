#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Registry of LiteDSP blocks to run through the FPGA implementation flows.

Each factory returns ``(dut, ios, clock_ns)``: the module, the set of port signals to expose as
top-level IOs (sink/source + controls), and the target clock period for fmax constraints.
"""

import numpy as np

from litedsp.generation.nco       import NCO
from litedsp.generation.cordic    import CORDIC
from litedsp.mixing.mixer         import Mixer
from litedsp.mixing.ddc           import DDC
from litedsp.mixing.duc           import DUC
from litedsp.mixing.channelizer   import Channelizer
from litedsp.filter.fir           import FIRFilterComplex
from litedsp.filter.fir_poly      import FIRDecimator, FIRInterpolator
from litedsp.filter.cic           import CICDecimator, CICInterpolator
from litedsp.filter.halfband      import HalfbandDecimator
from litedsp.filter.iir_biquad    import IIRBiquadCascade
from litedsp.filter.dc_blocker    import DCBlocker
from litedsp.filter.moving_average import MovingAverage
from litedsp.filter.farrow        import FarrowInterpolator
from litedsp.filter.equalizer     import LMSEqualizer
from litedsp.filter.design        import biquad_sos_quantize
from litedsp.level.gain           import Gain
from litedsp.level.power          import Power
from litedsp.level.agc            import AGC
from litedsp.level.saturate       import Saturate
from litedsp.level.rms            import RMS
from litedsp.analysis.magnitude   import Magnitude
from litedsp.analysis.window      import Window
from litedsp.analysis.fft         import FFT
from litedsp.analysis.fft_iter    import FFTIter
from litedsp.analysis.psd         import PSD
from litedsp.analysis.goertzel    import Goertzel
from litedsp.analysis.stats       import Stats
from litedsp.analysis.histogram   import Histogram
from litedsp.stream.combine       import Combine
from litedsp.stream.fifo          import StreamFIFO
from litedsp.stream.adapt         import IQPack, IQUnpack
from litedsp.stream.csr_io        import CSRSource, CSRSink, NullSink
from litedsp.stream.framing       import StreamFramer
from litedsp.generation.pattern   import PatternSource
from litedsp.analysis.measure     import ErrorCounter
from litedsp.comm.fm_demod        import FMDemod
from litedsp.comm.timing_recovery import TimingRecovery
from litedsp.comm.correlator      import Correlator

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
    d = NCO(data_width=16, with_csr=False)
    return d, {d.phase_inc} | _eps(d.source), 10.0

def nco_qw():
    d = NCO(data_width=16, quarter_wave=True, with_csr=False)
    return d, {d.phase_inc} | _eps(d.source), 10.0

def cordic_rot():
    d = CORDIC(data_width=16, mode="rotation", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def cordic_vec():
    d = CORDIC(data_width=16, mode="vectoring", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def mixer():
    d = Mixer(data_width=16, with_csr=False)
    return d, {d.mode, d.bypass} | _eps(d.sink_a, d.sink_b, d.source), 10.0

def fir_complex():
    d = FIRFilterComplex(n_taps=32, data_width=16, with_csr=False)
    return d, {d.bypass} | _eps(d.sink, d.source), 10.0

def fir_decimator():
    d = FIRDecimator(32, 8, data_width=16, with_csr=False)
    return d, {d.coeff_data, d.coeff_we, d.coeff_rst} | _eps(d.sink, d.source), 10.0

def fir_interpolator():
    d = FIRInterpolator(32, 8, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def cic_decimator():
    d = CICDecimator(data_width=16, R=8, N=4, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def cic_interpolator():
    d = CICInterpolator(data_width=16, R=8, N=4, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def halfband():
    d = HalfbandDecimator(n_taps=23, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def iir_biquad():
    sos, frac = _lowpass_sos(3)
    d = IIRBiquadCascade(data_width=16, sections=sos, frac_bits=frac, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def dc_blocker():
    d = DCBlocker(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def moving_average():
    d = MovingAverage(data_width=16, length_log2=5, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def farrow():
    d = FarrowInterpolator(data_width=16, with_csr=False)
    return d, {d.mu} | _eps(d.sink, d.source), 10.0

def gain():
    d = Gain(data_width=16, with_csr=False)
    return d, {d.gain, d.shift, d.bypass, d.clear_sat} | _eps(d.sink, d.source), 10.0

def power():
    d = Power(data_width=16, with_csr=False)
    return d, {d.window_log2} | _eps(d.sink, d.source), 10.0

def agc():
    d = AGC(data_width=16, with_csr=False)
    return d, {d.target} | _eps(d.sink, d.source), 10.0

def saturate():
    d = Saturate(data_width=16, in_width=32, shift=15, with_csr=False)
    return d, {d.clear_sat} | _eps(d.sink, d.source), 10.0

def rms():
    d = RMS(data_width=16, window_log2=8, with_csr=False)
    return d, {d.window_log2} | _eps(d.sink, d.source), 10.0

def magnitude():
    d = Magnitude(data_width=16, method="approx", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def magnitude_cordic():
    d = Magnitude(data_width=16, method="cordic", with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def combine():
    d = Combine(n_channels=4, data_width=16, with_csr=False)
    return d, {d.enable} | _eps(d.source, *d.sinks), 10.0

def window():
    d = Window(256, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def fft():
    d = FFT(256, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def fft_iter():
    d = FFTIter(256, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def psd():
    d = PSD(256, latency=255, data_width=16, avg_log2=4, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def goertzel():
    d = Goertzel(64, 5, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def stats():
    d = Stats(data_width=16, window_log2=8, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def histogram():
    d = Histogram(data_width=16, bits=8, window_log2=12, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def ddc():
    d = DDC(data_width=16, decimation=8, method="fir", with_csr=False)
    return d, {d.nco.phase_inc} | _eps(d.sink, d.source), 10.0

def duc():
    d = DUC(data_width=16, interpolation=8, method="fir", with_csr=False)
    return d, {d.nco.phase_inc} | _eps(d.sink, d.source), 10.0

def channelizer():
    d = Channelizer(n_channels=4, decimation=4, data_width=16, method="fir", with_csr=False)
    return d, _eps(d.sink, *d.sources), 10.0

def lms_equalizer():
    d = LMSEqualizer(n_taps=7, data_width=16, with_csr=False)
    return d, {d.train} | _eps(d.sink, d.source), 12.0

def timing_recovery():
    d = TimingRecovery(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 12.0

def fm_demod():
    d = FMDemod(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def correlator():
    d = Correlator([1, 1, 1, -1, -1, 1, -1], data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def stream_fifo():
    d = StreamFIFO(depth=16, data_width=16, with_csr=False)
    return d, {d.level, d.overflow} | _eps(d.sink, d.source), 8.0

def iq_pack():
    d = IQPack(ratio=4, data_width=16)
    return d, _eps(d.sink, d.source), 8.0

def iq_unpack():
    d = IQUnpack(ratio=4, data_width=16)
    return d, _eps(d.sink, d.source), 8.0

def csr_source():
    d = CSRSource(data_width=16, with_csr=False)
    return d, {d.i, d.q, d.push} | _eps(d.source), 8.0

def csr_sink():
    d = CSRSink(data_width=16, with_csr=False)
    return d, {d.last_i, d.last_q, d.count, d.clear} | _eps(d.sink), 8.0

def null_sink():
    d = NullSink(data_width=16, with_csr=False)
    return d, {d.count, d.clear} | _eps(d.sink), 8.0

def pattern_source():
    d = PatternSource(data_width=16, with_csr=False)
    return d, {d.mode, d.const_i, d.const_q} | _eps(d.source), 8.0

def error_counter():
    d = ErrorCounter(data_width=16, with_csr=False)
    return d, {d.errors, d.total, d.clear} | _eps(d.sink_ref, d.sink_rx), 8.0

def framer():
    d = StreamFramer(length=256, data_width=16, with_csr=False)
    return d, {d.length} | _eps(d.sink, d.source), 8.0

# Registry -----------------------------------------------------------------------------------------

REGISTRY = {
    "nco": nco, "nco_qw": nco_qw, "cordic_rot": cordic_rot, "cordic_vec": cordic_vec,
    "mixer": mixer, "fir_complex": fir_complex, "fir_decimator": fir_decimator,
    "fir_interpolator": fir_interpolator, "cic_decimator": cic_decimator,
    "cic_interpolator": cic_interpolator, "halfband": halfband, "iir_biquad": iir_biquad,
    "dc_blocker": dc_blocker, "moving_average": moving_average, "farrow": farrow,
    "gain": gain, "power": power, "agc": agc, "saturate": saturate, "rms": rms,
    "magnitude": magnitude, "magnitude_cordic": magnitude_cordic, "combine": combine,
    "window": window, "fft": fft, "fft_iter": fft_iter, "psd": psd, "goertzel": goertzel,
    "stats": stats, "histogram": histogram, "ddc": ddc, "duc": duc, "channelizer": channelizer,
    "lms_equalizer": lms_equalizer, "timing_recovery": timing_recovery, "fm_demod": fm_demod,
    "correlator": correlator,
    "stream_fifo": stream_fifo, "iq_pack": iq_pack, "iq_unpack": iq_unpack,
    "csr_source": csr_source, "csr_sink": csr_sink, "null_sink": null_sink,
    "pattern_source": pattern_source, "error_counter": error_counter, "framer": framer,
}

# Subset for the slower full place-&-route flows.
PNR_SUBSET = ["nco", "mixer", "fir_complex", "fir_decimator", "cic_decimator",
              "iir_biquad", "fft", "cordic_vec", "ddc"]
