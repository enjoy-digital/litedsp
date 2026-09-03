#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Registry-driven parameter validation: invalid constructor parameters raise ValueError.

Generic vectors are derived from each parameter's reflected kind (zero/negative widths and
factors); block-specific vectors cover the constraints the generic rules cannot guess. The
constructor contract (litedsp.common.check) survives ``python -O`` — unlike ``assert``.
"""

import unittest

from litedsp.flow import registry as flow_registry
from litedsp.flow.metadata import _accepts_with_csr

# Parameters where zero/negative values must be rejected when the block validates them.
NONPOSITIVE_REJECTED = {
    "n_taps", "decimation", "interpolation", "n_stages", "diff_delay", "lut_depth", "N",
    "fft_size", "n_samples", "n_channels", "depth", "modulus", "n_sum",
}

# Block-specific invalid vectors (beyond the generic non-positive rules).
SPECIFIC = [
    ("cic_decimator",   {"decimation": 1}),                # CIC needs >= 2.
    ("cic_interpolator", {"interpolation": 1}),
    ("nco",             {"lut_depth": 1000}),              # Power of two required.
    ("fft",             {"N": 100}),
    ("fft_iter",        {"N": 100}),
    ("parallel_fft",    {"N": 100}),
    ("parallel_fft",    {"N": 4}),                         # Power of two >= 8 required.
    ("parallel_fft",    {"n_samples": 4}),                 # Split default is P=2; native adds P=4.
    ("psd",             {"N": 100}),
    ("hilbert",         {"n_taps": 8}),                    # Odd taps required.
    ("decimator",       {"method": "invalid"}),
    ("interpolator",    {"method": "invalid"}),
    ("cp_insert",       {"cp_len": 0}),
    ("cp_insert",       {"cp_len": 64, "fft_size": 64}),   # cp_len < fft_size.
    ("cfr",             {"pulse_span": 7}),                # Even span required.
    ("cfr",             {"pulse_span": 2}),                # >= 4 required.
    ("cfr",             {"cutoff": 0.6}),                  # Normalized cutoff <= 0.5.
    ("dpd",             {"lut_depth": 100}),               # Power of two required.
    ("dpd",             {"lut_depth": 1 << 16}),           # log2(depth) <= data_width - 1.
    ("dpd",             {"coeff_frac": 0}),
    ("cordic_rot",      {"mode": "invalid"}),
    ("timing_recovery", {"ted": "invalid"}),
    ("magnitude",       {"method": "invalid"}),
    ("cfo_estimator",   {"delay": 12}),                    # Power of two required.
    ("cfo_estimator",   {"span_log2": 0}),
    ("block_interleaver",   {"rows": 0}),                  # Interleaving depth I >= 1.
    ("block_interleaver",   {"cols": 0}),
    ("block_deinterleaver", {"rows": 0}),
    ("block_deinterleaver", {"rows": 1, "cols": 1}),       # Block of at least 2 symbols.
    ("rs_encoder",      {"n": 254}),                       # n fixed at 255 over GF(2^8).
    ("rs_encoder",      {"k": 222}),                       # Odd n - k.
    ("rs_decoder",      {"k": 221}),                       # t = 17 > 16.
    ("clarke",          {"three_wire": "yes"}),            # Bool required.
    ("sincos",          {"method": "table"}),
    ("sincos",          {"lut_depth": 1000}),              # Power of two >= 8 required.
    ("sincos",          {"lut_depth": 1 << 17}),           # log2(depth) <= angle_width.
    ("angle_ramp",      {"phase_bits": 8}),                # phase_bits >= angle_width.
    ("pi_controller",   {"anti_windup": "hold"}),
    ("pi_controller",   {"gain_frac": 16}),                # gain_frac < gain_width.
    ("dq_controller",   {"decoupling": "yes"}),            # Bool required.
    ("svpwm",           {"injection": "third_harmonic"}),
    ("pwm",             {"period_width": 3}),              # >= 4 required.
    ("pwm",             {"dead_time_width": 0}),
    ("bitstream_decimator", {"decimation": 1}),
    ("bitstream_decimator", {"r_max": 8}),                 # r_max >= decimation.
    ("sigma_delta_filter", {"n_channels": 2}),             # 1 or 3 phases.
    ("sigma_delta_filter", {"fast_decimation": 1}),
    ("quadrature_decoder", {"filter_length": 0}),
    ("hall_decoder",    {"timer_width": 4}),               # >= 8 required.
    ("hall_decoder",    {"interpolate": "yes"}),           # Bool required.
    ("angle_tracker",   {"kp_shift": 32}),
    ("angle_tracker",   {"frac_bits": -1}),
    ("smo_observer",    {"gain_frac": 16}),
    ("resolver",        {"decimation": 2}),                # Excitation period >= 4 samples.
    ("foc",             {"anti_windup": "x"}),
    ("foc",             {"lut_depth": 1000}),
    ("volume",          {"ramp_shift": 0}),
    ("volume",          {"gain_frac": 23}),                # <= data_width - 2.
    ("stereo_matrix",   {"coeff_frac": 17}),               # < coeff_width - 1.
    ("dither",          {"out_width": 24}),                # < data_width.
    ("dither",          {"shaping": "ef3"}),
    ("dither",          {"seed": 0}),
    ("audio_eq",        {"frac_bits": 40}),                # < coeff_width.
    ("audio_eq",        {"error_feedback": 3}),
    ("audio_eq",        {"n_bands": 0}),
    ("exp2",            {"frac_bits": 16}),                # < in_width.
    ("exp2",            {"out_width": 20}),                # > out_frac.
    ("compressor",      {"preset": "expander"}),
    ("compressor",      {"lookahead": -1}),
    ("lfo",             {"lut_depth": 100}),
    ("delay_line",      {"max_delay": 2}),
    ("delay_line",      {"coeff_frac": 16}),
    ("reverb",          {"comb_delays": ()}),
    ("reverb",          {"allpass_delays": (2,)}),
    ("peak_meter",      {"decay_shift": 16}),
    ("loudness",        {"hop_samples": 0}),
    ("sigma_delta_mod", {"order": 3}),
    ("sigma_delta_dac", {"clk_div": 3}),
    ("pdm_rx",          {"n_channels": 3, "dual_edge": True}),
    ("i2s_rx",          {"fmt": "bad"}),
    ("i2s_rx",          {"slot_width": 20}),
    ("i2s_tx",          {"bclk_div": 3}),
    ("bit_reverse",     {"N": 100}),
    ("range_gate",      {"gate_start": 1000}),
    ("range_gate",      {"pri": 1}),
    ("pulse_compressor", {"pulse_len": 1}),
    ("pulse_compressor", {"window": "kaiser"}),
    ("mti",             {"order": 4}),
    ("corner_turn",     {"n_pulses": 1}),
    ("doppler",         {"n_pulses": 12}),
    ("doppler",         {"magnitude": "cordic"}),
]

class TestParams(unittest.TestCase):
    def _build(self, spec, override):
        kwargs = dict(spec.kwargs)
        kwargs.update(override)
        if _accepts_with_csr(spec.cls):
            kwargs["with_csr"] = False
        return spec.cls(**kwargs)

    def test_specific_invalid_vectors(self):
        palette = flow_registry.registry()
        for key, bad in SPECIFIC:
            with self.subTest(block=key, kwargs=bad):
                with self.assertRaises(ValueError):
                    self._build(palette[key], bad)

    def test_generic_nonpositive_rejected(self):
        # For every int parameter in the rejected vocabulary, 0 (or -1) must not silently
        # produce a block. ValueError is the contract; blocks that currently accept the
        # value are reported so validation coverage can only grow.
        palette  = flow_registry.registry()
        accepted = []
        for key, spec in sorted(palette.items()):
            for p in spec.params:
                if p.kind != "int" or p.name not in NONPOSITIVE_REJECTED:
                    continue
                bad = -1 if p.name == "depth" else 0
                try:
                    self._build(spec, {p.name: bad})
                    accepted.append(f"{key}.{p.name}")
                except ValueError:
                    pass
                except Exception as e:
                    # Crashing with a random exception is not a contract; record it.
                    accepted.append(f"{key}.{p.name} ({type(e).__name__})")
        known = ALLOWED_UNVALIDATED
        new   = sorted(set(accepted) - known)
        self.assertFalse(new,
            f"parameters accepting 0 without ValueError (add check() or allowlist): {new}")
        gone = sorted(known - set(accepted))
        self.assertFalse(gone,
            f"allowlisted entries now validate (remove from ALLOWED_UNVALIDATED): {gone}")

# Parameters that currently accept 0 (or fail non-ValueError); each is a candidate for a
# validation fix. This list may only shrink.
ALLOWED_UNVALIDATED = set()

if __name__ == "__main__":
    unittest.main()
