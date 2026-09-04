#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.generation.source import LiteDSPChirp
from litedsp.radar.waveform    import (chirp_words, chirp_reference, pulse_compressor_taps,
                                       window_taper)

from test.common import run_stream, column

class TestChirpReference(unittest.TestCase):
    # verify-tier: model — the NumPy replica equals the LiteDSPChirp hardware output sample for
    # sample for two bandwidths (the replica is what the pulse compressor's taps are built from).
    def test_matches_hardware(self):
        for bandwidth in (0.5, 0.125):
            with self.subTest(bandwidth=bandwidth):
                P = 32
                dut = LiteDSPChirp(with_csr=False)
                dut.start.reset, dut.rate.reset = chirp_words(bandwidth, P)
                cap = run_stream(dut, None, P, [], ["i", "q"], source_ready_rate=1.0)
                got = column(cap, "i", 16) + 1j*column(cap, "q", 16)
                ref = chirp_reference(P, bandwidth)
                self.assertTrue(np.array_equal(got, ref))

    def test_sweep_and_taps(self):
        s = chirp_reference(64, 0.5)
        phase = np.unwrap(np.angle(s))
        f = np.diff(phase)/(2*np.pi)                                # Instantaneous frequency.
        self.assertLess(f[0], -0.2)
        self.assertGreater(f[-1], 0.2)
        re, im = pulse_compressor_taps(16, 0.5, window="hamming")
        self.assertEqual((len(re), len(im)), (16, 16))
        self.assertTrue(all(abs(v) <= 32767 for v in re + im))
        self.assertLess(abs(re[0]), abs(re[8]))                    # Taper lowers the edges.
        self.assertEqual(window_taper("rect", 5).tolist(), [1.0]*5)
        for kwargs in ({"bandwidth": 0.0}, {"bandwidth": 1.5}, {"pulse_len": 1}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                chirp_words(**kwargs)
        with self.assertRaises(ValueError):
            pulse_compressor_taps(16, 0.5, window="kaiser")

if __name__ == "__main__":
    unittest.main()
