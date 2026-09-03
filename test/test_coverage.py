#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import json
import tempfile
import unittest

from sim.run_coverage import load_waivers


class TestCoverageWaivers(unittest.TestCase):
    def test_semantic_checks_resolve(self):
        waivers = load_waivers()
        self.assertEqual(set(waivers), {
            "equalizer", "fir_decimator", "fir_decimator_pipelined", "fir_interpolator",
            "fir_interpolator_pipelined",
            "ldpc_decoder", "ldpc_decoder_z_parallel", "pfb_channelizer_fft",
            "pfb_channelizer_fft_2x",
            # Motor / audio composites: nested reset arms, hard-wired mixer modes, internal
            # bypass paths and the limiter's peak-only sidechain (see the waiver reasons).
            "sincos_cordic", "park", "inverse_park", "dq_controller", "bitstream_decimator",
            "sigma_delta_filter", "smo_observer", "foc", "reverb", "compressor_limiter",
            # Radar composites (nested FIR / window / FFT / magnitude / reorder arms).
            "pulse_compressor", "pulse_compressor_hamming", "pulse_compressor_mac", "doppler",
            "doppler_power", "monopulse", "beamformer", "beamformer_2beams", "tvg", "pixel_pattern", "line_buffer", "kernel_2d", "kernel_5x5", "gaussian_blur",
            "sharpen", "laplacian", "color_matrix", "rgb_to_ycbcr", "ycbcr_to_rgb", "rgb_to_gray", "debayer", "box_overlay", "manchester_decoder",
        })
        self.assertGreaterEqual(len(waivers["ldpc_decoder"]["semantic_checks"]), 5)

    def test_unresolved_check_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json") as f:
            json.dump({"bad": {"reason": "test", "semantic_checks": [
                "test.test_ldpc:TestLDPC.not_a_test"]}}, f)
            f.flush()
            with self.assertRaises(ValueError):
                load_waivers(f.name)


if __name__ == "__main__":
    unittest.main()
