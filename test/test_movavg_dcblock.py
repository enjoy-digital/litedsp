#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.filter.dc_blocker     import DCBlocker
from litedsp.filter.moving_average import MovingAverage

from test.common import run_stream, column
from test.models import dc_blocker_model, moving_average_model

class TestMovingAverage(unittest.TestCase):
    def test_bit_exact(self):
        for length_log2 in [1, 3, 5]:
            dut = MovingAverage(data_width=16, length_log2=length_log2, with_csr=False)
            prng = random.Random(length_log2)
            xi = [prng.randint(-30000, 30000) for _ in range(300)]
            xq = [prng.randint(-30000, 30000) for _ in range(300)]
            samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
            cap = run_stream(dut, samples, len(xi), ["i", "q"], ["i", "q"],
                sink_throttle=0.2, source_ready_rate=0.7)
            self.assertTrue(np.array_equal(column(cap, "i", 16), moving_average_model(xi, length_log2)))
            self.assertTrue(np.array_equal(column(cap, "q", 16), moving_average_model(xq, length_log2)))

    def test_dc_passes(self):
        # Constant input -> output settles to that constant.
        dut = MovingAverage(data_width=16, length_log2=4, with_csr=False)
        n = 64
        cap = run_stream(dut, [{"i": 5000, "q": -3000} for _ in range(n)], n, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        self.assertEqual(column(cap, "i", 16)[-1], 5000)
        self.assertEqual(column(cap, "q", 16)[-1], -3000)

class TestDCBlocker(unittest.TestCase):
    def test_bit_exact(self):
        for pole_shift in [3, 5, 8]:
            dut = DCBlocker(data_width=16, pole_shift=pole_shift, with_csr=False)
            prng = random.Random(pole_shift)
            xi = [prng.randint(-20000, 20000) for _ in range(300)]
            xq = [prng.randint(-20000, 20000) for _ in range(300)]
            samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
            cap = run_stream(dut, samples, len(xi), ["i", "q"], ["i", "q"],
                sink_throttle=0.2, source_ready_rate=0.7)
            self.assertTrue(np.array_equal(column(cap, "i", 16), dc_blocker_model(xi, pole_shift)))
            self.assertTrue(np.array_equal(column(cap, "q", 16), dc_blocker_model(xq, pole_shift)))

    def test_removes_dc(self):
        # Tone on a large DC offset: output DC should be strongly attenuated.
        n = 4000
        t = np.arange(n)
        x = (8000 + 4000*np.cos(2*np.pi*0.05*t)).astype(int)
        dut = DCBlocker(data_width=16, pole_shift=6, with_csr=False)
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        out = column(cap, "i", 16)[n//2:]   # Skip settling.
        self.assertLess(abs(out.mean()), 50)          # DC removed.
        self.assertGreater(out.std(), 2000)           # AC preserved.

if __name__ == "__main__":
    unittest.main()
