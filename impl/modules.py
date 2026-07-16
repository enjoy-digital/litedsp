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
from litedsp.analysis.fft         import LiteDSPFFT
from litedsp.analysis.fft_iter    import LiteDSPFFTIter
from litedsp.analysis.fft_parallel import LiteDSPParallelFFT
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
from litedsp.comm.rs              import LiteDSPRSEncoder, LiteDSPRSDecoder
from litedsp.comm.ldpc            import LiteDSPLDPCEncoder, LiteDSPLDPCDecoder

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
    d = LiteDSPFIRDecimator(n_taps=32, decimation=8, data_width=16, with_csr=False)
    return d, {d.coeff_data, d.coeff_we, d.coeff_rst} | _eps(d.sink, d.source), 10.0

def fir_interpolator():
    d = LiteDSPFIRInterpolator(n_taps=32, interpolation=8, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def resampler_farm():
    d = LiteDSPResamplerFarm(n_channels=4, n_taps=32, decimation=8, data_width=16, with_csr=False)
    return d, {d.coeff_data, d.coeff_we, d.coeff_rst} | _eps(d.source, *d.sinks), 10.0

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

def dc_blocker():
    d = LiteDSPDCBlocker(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

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
    d = LiteDSPAGC(data_width=16, with_csr=False, delayed_feedback=True)
    return d, {d.target} | _eps(d.sink, d.source), 10.0

def dpd():
    d = LiteDSPDPD(data_width=16, n_taps=3, lut_depth=64, coeff_frac=14, with_csr=False)
    return d, {d.lut_tap, d.lut_data, d.lut_we, d.lut_rst, d.bypass} | _eps(d.sink, d.source), 10.0

def cfr():
    d = LiteDSPCFR(data_width=16, pulse_span=16, with_csr=False)
    # Expose the counters too, or the detection path folds away.
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

def fft_iter():
    d = LiteDSPFFTIter(256, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def psd():
    d = LiteDSPPSD(256, data_width=16, avg_log2=4, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def goertzel():
    d = LiteDSPGoertzel(64, 5, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def stats():
    d = LiteDSPStats(data_width=16, window_log2=8, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def histogram():
    d = LiteDSPHistogram(data_width=16, bits=8, window_log2=12, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def ddc():
    d = LiteDSPDDC(data_width=16, decimation=8, method="fir", with_csr=False)
    return d, {d.nco.phase_inc} | _eps(d.sink, d.source), 10.0

def duc():
    d = LiteDSPDUC(data_width=16, interpolation=8, method="fir", with_csr=False)
    return d, {d.nco.phase_inc} | _eps(d.sink, d.source), 10.0

def channelizer():
    d = LiteDSPChannelizer(n_channels=4, decimation=4, data_width=16, method="fir", with_csr=False)
    return d, _eps(d.sink, *d.sources), 10.0

def pfb_channelizer():
    d = LiteDSPPFBChannelizer(n_channels=4, taps_per_channel=8, data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def lms_equalizer():
    d = LiteDSPLMSEqualizer(n_taps=7, data_width=16, with_csr=False)
    return d, {d.train} | _eps(d.sink, d.source), 12.0

def timing_recovery():
    d = LiteDSPTimingRecovery(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 12.0

def fm_demod():
    d = LiteDSPFMDemod(data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def correlator():
    d = LiteDSPCorrelator([1, 1, 1, -1, -1, 1, -1], data_width=16, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def frame_sync():
    d = LiteDSPFrameSync([1, 1, 1, -1, -1, 1, -1], data_width=16, frame_len=64, with_csr=False)
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
    d = LiteDSPViterbiDecoder(with_csr=False)                # Hard-decision, K=7 (171, 133).
    return d, _eps(d.sink, d.source), 12.0

def viterbi_decoder_soft():
    d = LiteDSPViterbiDecoder(llr_bits=4, with_csr=False)    # Soft-decision, 4-bit LLRs.
    return d, _eps(d.sink, d.source), 12.0

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
    d = LiteDSPRSDecoder(with_csr=False)                     # RS(255,223), t=16.
    return d, {d.corrected, d.corrected_total, d.uncorrectable, d.uncorrectable_count,
               d.clear} | _eps(d.sink, d.source), 12.0

def ldpc_encoder():
    d = LiteDSPLDPCEncoder(with_csr=False)                   # 802.11n (648, 324), z=27.
    return d, _eps(d.sink, d.source), 10.0

def ldpc_decoder():
    d = LiteDSPLDPCDecoder(llr_bits=4, max_iters=8, with_csr=False)  # Layered min-sum.
    return d, {d.iterations, d.parity_ok, d.failures, d.clear} | _eps(d.sink, d.source), 12.0

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

def cic_parallel_x4():
    d = LiteDSPParallelCICDecimator(n_samples=4, data_width=16, decimation=8, n_stages=4, with_csr=False)
    return d, _eps(d.sink, d.source), 10.0

def ddc_parallel_x4():
    d = LiteDSPParallelDDC(n_samples=4, data_width=16, decimation=8, with_csr=False)
    return d, {d.nco.phase_inc} | _eps(d.sink, d.source), 10.0

def fft_parallel_x2():
    d = LiteDSPParallelFFT(N=256, data_width=16, with_csr=False)   # Same N as the serial fft entry.
    return d, _eps(d.sink, d.source), 10.0

# Registry -----------------------------------------------------------------------------------------

REGISTRY = {
    "nco": nco, "nco_qw": nco_qw, "cordic_rot": cordic_rot, "cordic_vec": cordic_vec,
    "mixer": mixer, "fir_complex": fir_complex, "fir_decimator": fir_decimator,
    "fir_interpolator": fir_interpolator, "resampler_farm": resampler_farm,
    "cic_decimator": cic_decimator,
    "cic_interpolator": cic_interpolator, "halfband": halfband, "iir_biquad": iir_biquad,
    "dc_blocker": dc_blocker, "moving_average": moving_average, "farrow": farrow,
    "gain": gain, "power": power, "agc": agc, "dpd": dpd, "cfr": cfr, "saturate": saturate, "rms": rms,
    "magnitude": magnitude, "magnitude_cordic": magnitude_cordic, "combine": combine,
    "window": window, "fft": fft, "fft_iter": fft_iter, "psd": psd, "goertzel": goertzel,
    "stats": stats, "histogram": histogram, "ddc": ddc, "duc": duc, "channelizer": channelizer,
    "pfb_channelizer": pfb_channelizer,
    "lms_equalizer": lms_equalizer, "timing_recovery": timing_recovery, "fm_demod": fm_demod,
    "correlator": correlator, "frame_sync": frame_sync, "cfo_estimator": cfo_estimator,
    "soft_demapper": soft_demapper, "ofdm_equalizer": ofdm_equalizer,
    "puncturer": puncturer, "depuncturer": depuncturer,
    "viterbi_decoder": viterbi_decoder, "viterbi_decoder_soft": viterbi_decoder_soft,
    "block_interleaver": block_interleaver, "block_deinterleaver": block_deinterleaver,
    "rs_encoder": rs_encoder, "rs_decoder": rs_decoder,
    "ldpc_encoder": ldpc_encoder, "ldpc_decoder": ldpc_decoder,
    "stream_fifo": stream_fifo, "iq_pack": iq_pack, "iq_unpack": iq_unpack,
    "csr_source": csr_source, "csr_sink": csr_sink, "null_sink": null_sink,
    "pattern_source": pattern_source, "error_counter": error_counter, "framer": framer,
    "fir": fir,
    "nco_parallel_x2": nco_parallel_x2, "nco_parallel_x4": nco_parallel_x4,
    "mixer_parallel_x2": mixer_parallel_x2, "mixer_parallel_x4": mixer_parallel_x4,
    "fir_parallel_x2": fir_parallel_x2, "fir_parallel_x4": fir_parallel_x4,
    "cic_parallel_x4": cic_parallel_x4, "ddc_parallel_x4": ddc_parallel_x4,
    "fft_parallel_x2": fft_parallel_x2,
}

# Subset for the slower full place-&-route flows.
PNR_SUBSET = ["nco", "mixer", "fir_complex", "fir_decimator", "cic_decimator",
              "cic_interpolator", "iir_biquad", "fft", "cordic_vec", "agc", "dpd", "ddc",
              "channelizer", "ldpc_decoder", "mixer_parallel_x2", "farrow", "window"]

# Blocks whose reviewed engineering target is already closed and therefore strict in CI.
# Other explicit targets remain visible objectives until their architecture work lands.
TARGET_CLOSED = ["dpd", "ddc", "channelizer", "ldpc_decoder",
                 "cic_decimator", "cic_interpolator", "agc"]

# Modules whose exposed ports exceed device pins: synthesis-only (skipped by the P&R flow).
SYNTH_ONLY = ["fir", "fir_parallel_x2", "fir_parallel_x4", "mixer_parallel_x4"]
