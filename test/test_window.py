#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.analysis.window import Window, window_coefficients

from test.common import run_stream, column
from test.models import window_model

class TestWindow(unittest.TestCase):
    def run_window(self, xi, xq, n, window, data_width=16):
        dut = Window(n=n, data_width=data_width, window=window, with_csr=False)
        samples  = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
        captured = run_stream(dut, samples, len(xi), ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        return column(captured, "i", data_width), column(captured, "q", data_width)

    def test_bit_exact(self):
        n    = 64
        prng = random.Random(1)
        xi   = [prng.randint(-30000, 30000) for _ in range(n*3)]
        xq   = [prng.randint(-30000, 30000) for _ in range(n*3)]
        for window in ["rect", "hann", "hamming", "blackman"]:
            gi, gq = self.run_window(xi, xq, n, window)
            coeffs = window_coefficients(n, window)
            ri, rq = window_model(xi, xq, coeffs)
            self.assertTrue(np.array_equal(gi, ri[:len(gi)]), f"{window} I mismatch")
            self.assertTrue(np.array_equal(gq, rq[:len(gq)]), f"{window} Q mismatch")

    def test_coherent_gain(self):
        # DC input through Hann: total output energy ~= DC * sum(coeffs)/2**15 (coherent gain).
        n  = 64
        dc = 20000
        gi, _  = self.run_window([dc]*(n*2), [0]*(n*2), n, "hann")
        coeffs = np.array(window_coefficients(n, "hann"))
        got    = gi[:n].sum()
        ref    = (dc*coeffs/(1 << 15)).sum()
        self.assertLess(abs(got - ref)/abs(ref), 0.01)

if __name__ == "__main__":
    unittest.main()
