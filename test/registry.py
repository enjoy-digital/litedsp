#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Verification registry: per-block verification metadata over the flow palette.

The flow registry (:mod:`litedsp.flow.registry`) says what a block *is*; VSPEC says how it is
*verified*: which golden model backs it (``test/models.py``), how its latency is classified,
its rate contract, and whether it is eligible for Verilator co-simulation. The meta-test
(:mod:`test.test_registry_meta`) enforces completeness — a palette block without a VSPEC row,
or a golden model that is not bound here, fails CI. This is the ratchet that keeps
verification closed as blocks are added.

Fields
------
model : str or None
    Name of the backing golden model in ``test/models.py`` (bit-exact reference), if any.
latency : str
    ``"check"`` (fixed ``self.latency``, verified by test_latency), ``"variable"``
    (data-dependent, ``self.latency is None``), or ``"n/a"`` (source/sink-only blocks).
rate : tuple or None
    ``(out, in)`` steady-state samples-out per samples-in contract (None = data-dependent).
cosim : bool
    Eligible for Verilator bit-exact co-simulation (model-backed, standard stream shape).
"""

def _v(model=None, latency="check", rate=(1, 1), cosim=False):
    return {"model": model, "latency": latency, "rate": rate, "cosim": cosim}

VSPEC = {
    # generation (sources: no input -> latency n/a; rate = outputs only).
    "nco":                _v("nco_model",              latency="n/a", rate=None, cosim=True),
    "cordic_rot":         _v(latency="check"),
    "cordic_vec":         _v(latency="check"),
    "chirp":              _v(latency="n/a", rate=None),
    "noise_source":       _v(latency="n/a", rate=None),
    "pattern_source":     _v(latency="n/a", rate=None),
    # mixing.
    "mixer":              _v("mixer_model", cosim=True),
    "ddc":                _v(rate=None),                       # decimation-dependent.
    "duc":                _v(rate=None),
    "channelizer":        _v(rate=None),
    "pfb_channelizer":    _v("pfb_channelizer_model", rate=(1, 1), cosim=True),  # Critically sampled: M out per M in (framed).
    # filter.
    "fir_real":           _v("fir_model",              cosim=True),
    "fir_complex":        _v("fir_complex_model",      cosim=True),
    "fir_decimator":      _v("fir_decimator_model",    rate=(1, 8),  cosim=True),
    "fir_interpolator":   _v("fir_interpolator_model", rate=(8, 1),  cosim=True),
    "cic_decimator":      _v("cic_decimator_model",    rate=(1, 8),  cosim=True),
    "cic_interpolator":   _v("cic_interpolator_model", rate=(8, 1),  cosim=True),
    "halfband_dec":       _v(rate=(1, 2)),
    "halfband_int":       _v(rate=(2, 1)),
    "hilbert":            _v(),
    "iir_biquad":         _v("iir_biquad_model",       cosim=True),
    "dc_blocker":         _v("dc_blocker_model",       cosim=True),
    "moving_average":     _v("moving_average_model",   cosim=True),
    "farrow":             _v(),
    "equalizer":          _v("equalizer_model"),
    "notch":              _v(),
    "comb_filter":        _v(),
    "allpass":            _v(),
    "pulse_shaper":       _v(rate=None),
    "rational_resampler": _v(latency="variable", rate=(3, 2)),
    "arb_resampler":      _v(latency="variable", rate=None),
    # rate.
    "decimator":          _v(rate=(1, 8)),
    "interpolator":       _v(rate=(8, 1)),
    "downsampler":        _v("decimate_model",    rate=None, cosim=True),  # Runtime factor.
    "upsampler":          _v("interpolate_model", rate=None, cosim=True),
    "resampler_farm":     _v("farm_model",        rate=(1, 8)),  # Per channel; TDM-shared engine.
    # level.
    "gain":               _v("gain_model",  cosim=True),
    "power":              _v("power_model", latency="variable", rate=None),
    "agc":                _v("agc_model", cosim=True),
    "dpd":                _v("dpd_model"),             # Actuator only; adaptation is host-side.
    "cfr":                _v("cfr_model"),             # Single-engine peak cancellation.
    "saturate":           _v(),
    "clipper":            _v("clipper_model", cosim=True),
    "rms":                _v(latency="variable", rate=None),
    "squelch":            _v("squelch_model", cosim=True),
    "envelope":           _v("envelope_detector_model", cosim=True),
    "log2":               _v("log2_model", cosim=True),
    "log_power":          _v(),
    # correction.
    "dc_offset":          _v("dc_offset_model", cosim=True),
    "iq_balance":         _v(),
    "derotator":          _v(),
    # comm.
    "fm_demod":           _v(),
    "am_demod":           _v(),
    "slicer":             _v("slicer_model", cosim=True),
    "soft_demapper":      _v("soft_demap_model", cosim=True),
    "symbol_mapper":      _v(),
    "correlator":         _v("fir_complex_model", cosim=True),  # Matched filter = complex FIR.
    "frame_sync":         _v("frame_sync_model", cosim=True),  # CFAR preamble detect + alignment.
    "timing_recovery":    _v(latency="variable", rate=None),
    "carrier_loop":       _v(),
    "phase_detect":       _v(),
    "cfo_estimator":      _v("cfo_estimator_model"),     # Delay-conj-multiply + CORDIC angle.
    "diff_encoder":       _v("diff_encode_model", cosim=True),
    "diff_decoder":       _v("diff_decode_model", cosim=True),
    "scrambler":          _v(),
    "descrambler":        _v(),
    "crc":                _v(),
    "conv_encoder":       _v(),
    "viterbi_decoder":    _v("viterbi_model", cosim=True),
    "puncturer":          _v("puncture_model",   latency="variable", rate=None, cosim=True),  # Pattern-dependent.
    "depuncturer":        _v("depuncture_model", latency="variable", rate=None, cosim=True),
    "block_interleaver":  _v("block_interleave_model",   latency="variable", rate=(1, 1), cosim=True),  # 1:1, framed rows*cols blocks.
    "block_deinterleaver": _v("block_deinterleave_model", latency="variable", rate=(1, 1), cosim=True),
    "rs_encoder":         _v("rs_encode_model",  latency="variable", rate=None, cosim=True),  # k in -> n out (framed).
    "rs_decoder":         _v("rs_decode_model",  latency="variable", rate=None, cosim=True),  # n in -> k out (framed).
    "ldpc_encoder":       _v("ldpc_encode_model", latency="variable", rate=None, cosim=True),  # k bits in -> n bits out (framed).
    "ldpc_decoder":       _v("ldpc_decode_model", latency="variable", rate=None, cosim=True),  # n LLRs in -> k bits out (framed).
    "cp_insert":          _v(latency="variable", rate=None),
    "cp_remove":          _v(rate=None),
    "ofdm_equalizer":     _v("ofdm_equalizer_model", rate=None),  # 1:1 steady-state; training frames consumed.
    # analysis.
    "window":             _v("window_model", cosim=True),
    "fft":                _v("fft_model"),                     # SNR-thresholded (fixed point);
                                                               # scaling="bfp" is bit-exact vs
                                                               # fft_bfp_model (test_fft_bfp).
    "fft_iter":           _v(rate=None),
    "parallel_fft":       _v("parallel_fft_model", cosim=True),  # Bit-exact (= fft_fixed_model
                                                               # re-laned); 2-lane layout: no cosim.
    "psd":                _v("psd_model",   latency="variable", rate=None, cosim=True),
    "welch":              _v("welch_model", latency="variable", rate=None, cosim=True),
    "magnitude":          _v("magnitude_model", cosim=True),
    "magnitude_cordic":   _v(),
    "goertzel":           _v(latency="variable", rate=None),
    "stats":              _v(rate=None),
    "histogram":          _v(latency="variable", rate=None),
    "energy_detector":    _v(),
    "error_counter":      _v(latency="n/a", rate=None),        # Sink-only (CSR results).
    # stream.
    "combine":            _v("combine_model", cosim=True),
    "split":              _v(),
    "delay":              _v(),
    "skid_buffer":        _v(),
    "channel_mux":        _v(rate=None),
    "channel_demux":      _v(rate=None),
    "capture":            _v(latency="variable", rate=None),
    "conjugate":          _v("conjugate_model", cosim=True),
    "swap_iq":            _v("swap_iq_model", cosim=True),
    "negate":             _v("negate_model", cosim=True),
    "stream_fifo":        _v(),
    "iq_pack":            _v(rate=None),
    "iq_unpack":          _v(rate=None),
    "cdc":                _v(),
    "csr_source":         _v(latency="n/a", rate=None),
    "csr_sink":           _v(latency="n/a", rate=None),
    "null_sink":          _v(latency="n/a", rate=None),
    "framer":             _v(),
    "deframer":           _v(rate=None),
    "timestamper":        _v("timestamper_model"),        # Non-standard shape (param tags): no cosim.
    "time_untagger":      _v("time_untagger_model"),
}
