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
    "cordic_rot":         _v("cordic_rotation_model", cosim=True),   # Model shared with sincos.
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
    "dc_blocker_real":    _v("dc_blocker_model",       cosim=True),
    "moving_average":     _v("moving_average_model",   cosim=True),
    "farrow":             _v(),
    "equalizer":          _v("equalizer_model", cosim=True),
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
    "timing_recovery":    _v("timing_recovery_model", latency="variable", rate=None, cosim=True),
    "carrier_loop":       _v("carrier_loop_model", cosim=True),
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
    "ccsds_rs_encoder":   _v("ccsds_rs_encode_model", latency="variable", rate=None, cosim=True),
    "ccsds_rs_decoder":   _v("ccsds_rs_decode_model", latency="variable", rate=None, cosim=True),
    "ldpc_encoder":       _v("ldpc_encode_model", latency="variable", rate=None, cosim=True),  # k bits in -> n bits out (framed).
    "ldpc_decoder":       _v("ldpc_decode_model", latency="variable", rate=None, cosim=True),  # n LLRs in -> k bits out (framed).
    "ldpc_decoder_z_parallel": _v("ldpc_decode_model", latency="variable", rate=None, cosim=True),
    "cp_insert":          _v("cp_insert_model", latency="variable", rate=None, cosim=True),
    "cp_remove":          _v("cp_remove_model", rate=None, cosim=True),
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
    "bit_reverse":        _v("bit_reverse_model", latency="variable", cosim=True),
    "welch":              _v("welch_model", latency="variable", rate=None, cosim=True),
    "magnitude":          _v("magnitude_model", cosim=True),
    "magnitude_cordic":   _v(),
    "goertzel":           _v(latency="variable", rate=None),
    "stats":              _v(rate=None),
    "histogram":          _v(latency="variable", rate=None),
    "energy_detector":    _v(),
    "error_counter":      _v(latency="n/a", rate=None),        # Sink-only (CSR results).
    # motor (transforms are 1:1 maps; Park joins two sinks, so its cycle latency is pinned
    # in test_transforms rather than by the generic single-sink check).
    "clarke":             _v("clarke_model", cosim=True),
    "inverse_clarke":     _v("inverse_clarke_model", cosim=True),
    "sincos":             _v("sincos_model", cosim=True),
    "angle_ramp":         _v("angle_ramp_model", latency="n/a", rate=None, cosim=True),
    "park":               _v("park_model", cosim=True),
    "inverse_park":       _v("inverse_park_model", cosim=True),
    "pi_controller":      _v("pi_controller_model", cosim=True),
    "dq_controller":      _v("dq_controller_model", cosim=True),
    "slew_limiter":       _v("slew_limiter_model", cosim=True),
    "svpwm":              _v("svpwm_model", cosim=True),
    "pwm":                _v("pwm_model", latency="n/a", rate=None),   # Sink-only, pin outputs.
    "bitstream_decimator": _v("bitstream_decimator_model", rate=None, cosim=True),  # Runtime rate.
    "sigma_delta_filter": _v("sigma_delta_filter_model", rate=None, cosim=True),
    "overcurrent_trip":   _v("overcurrent_trip_model", cosim=True),
    "quadrature_decoder": _v("quadrature_decoder_model", latency="n/a", rate=None),  # Pin-driven.
    "hall_decoder":       _v("hall_sector_model", latency="n/a", rate=None),
    "angle_tracker":      _v("angle_tracker_model", cosim=True),
    "smo_observer":       _v("smo_model", cosim=True),
    "resolver":           _v("resolver_model", rate=None),     # Two sources: no generic cosim.
    "foc":                _v("foc_model", cosim=True),
    # audio (channel-tagged TDM streams, 24-bit).
    "volume":             _v("volume_model", cosim=True),
    "stereo_matrix":      _v("stereo_matrix_model", cosim=True),   # Serial engine: 2 beats in, 2 out.
    "dither":             _v("dither_model", cosim=True),
    "audio_eq":           _v("audio_eq_model", cosim=True),
    "exp2":               _v("exp2_model", cosim=True),
    "compressor":         _v("compressor_model", cosim=True),
    "limiter":            _v("compressor_model"),               # Same class (preset); cosim variant.
    "noise_gate":         _v("compressor_model"),
    "lfo":                _v("lfo_model", latency="n/a", rate=None, cosim=True),
    "delay_line":         _v("delay_line_model", cosim=True),
    "chorus":             _v("delay_line_model"),               # Modulation sink consumed once per
                                                               # frame: not generic-TB co-simulable.
    "wet_dry_mix":        _v("wet_dry_mix_model", cosim=True),
    "reverb":             _v("reverb_model", cosim=True),       # Cosim spec uses short delays.
    "peak_meter":         _v("peak_meter_model"),               # CSR read-back meters: passthrough
    "loudness":           _v("loudness_model"),                 # taps, measurements not on the stream.
    "sigma_delta_mod":    _v("sigma_delta_model", rate=(64, 1), cosim=True),
    "sigma_delta_dac":    _v("sigma_delta_model", latency="n/a", rate=None),   # Sink-only (pins).
    "pdm_rx":             _v("pdm_receiver_model", latency="n/a", rate=None),  # Source-only (pins).
    "i2s_rx":             _v("i2s_frame_model", latency="n/a", rate=None),     # Pin-level source.
    "i2s_tx":             _v("i2s_frame_model", latency="n/a", rate=None),     # Pin-level sink.
    "pulse_generator":    _v("pulse_generator_model", latency="n/a", rate=None, cosim=True),
    "range_gate":         _v("range_gate_model", latency="check", rate=None, cosim=True),
    "pulse_compressor":   _v("pulse_compressor_model", cosim=True),
    "mti":                _v("mti_model", cosim=True),
    "corner_turn":        _v("corner_turn_model", latency="variable", cosim=True),
    "doppler":            _v("doppler_model", latency="variable", cosim=True),
    "ca_cfar":            _v("ca_cfar_model", latency="variable", cosim=True),
    "cfar_2d":            _v("cfar_2d_model", latency="variable", cosim=True),
    "os_cfar":            _v("os_cfar_model", latency="variable", cosim=True),
    "clutter_map":        _v("clutter_map_model", latency=4, cosim=True),
    "peak_extractor":     _v("peak_extractor_model", latency="variable", cosim=True),
    "target_list":        _v("target_list_model", latency="variable", cosim=True),
    "alpha_beta_tracker": _v("alpha_beta_tracker_model", latency="variable", cosim=True),
    "kalman_tracker":     _v("kalman_tracker_model", latency="variable", cosim=True),
    "beamformer":         _v("beamformer_model", latency=3, cosim=True),
    "monopulse":          _v("monopulse_model", latency=21, cosim=True),
    "tvg":                _v("tvg_model", latency=6, cosim=True),
    # stream.
    "combine":            _v("combine_model", cosim=True),
    "split":              _v(),
    "delay":              _v(),
    "skid_buffer":        _v(),
    "channel_mux":        _v(rate=None),
    "channel_demux":      _v(rate=None),
    "tdm_mux":            _v("tdm_mux_model", cosim=True),    # Round-robin interleave (2 sinks).
    "tdm_demux":          _v(rate=None),
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
