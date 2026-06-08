#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.level.gain import Gain

from test.common import run_stream, column
from test.models import gain_model

class TestGain(unittest.TestCase):
    def run_gain(self, x_i, x_q, gain, shift, bypass=0, data_width=16):
        n   = len(x_i)
        dut = Gain(data_width=data_width, with_csr=False)
        dut.gain.reset   = gain
        dut.shift.reset  = shift
        dut.bypass.reset = bypass
        samples  = [{"i": x_i[k], "q": x_q[k]} for k in range(n)]
        captured = run_stream(dut, samples, n, ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        return column(captured, "i", data_width), column(captured, "q", data_width)

    def rand_iq(self, n, seed, amp=20000):
        prng = random.Random(seed)
        return ([prng.randint(-amp, amp) for _ in range(n)],
                [prng.randint(-amp, amp) for _ in range(n)])

    def test_unity(self):
        xi, xq = self.rand_iq(200, 1)
        gi, gq = self.run_gain(xi, xq, gain=(1 << 14), shift=0)   # 1.0 in Q2.14.
        ri, rq = gain_model(xi, xq, 1 << 14, 0)
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))

    def test_various_gains(self):
        xi, xq = self.rand_iq(200, 2)
        for gain, shift in [(1 << 13, 0), (3 << 13, 0), (1 << 14, 1), (1 << 14, 3), (1 << 15, 0)]:
            gi, gq = self.run_gain(xi, xq, gain=gain, shift=shift)
            ri, rq = gain_model(xi, xq, gain, shift)
            self.assertTrue(np.array_equal(gi, ri), f"I mismatch gain={gain} shift={shift}")
            self.assertTrue(np.array_equal(gq, rq), f"Q mismatch gain={gain} shift={shift}")

    def test_bypass(self):
        xi, xq = self.rand_iq(128, 3)
        gi, gq = self.run_gain(xi, xq, gain=(3 << 14), shift=0, bypass=1)
        self.assertTrue(np.array_equal(gi, np.array(xi)))
        self.assertTrue(np.array_equal(gq, np.array(xq)))

    def test_saturation_flag(self):
        # Large samples with gain ~4 must overflow and set the sticky flag.
        n   = 64
        dut = Gain(data_width=16, with_csr=False)
        dut.gain.reset  = (1 << 14)*4    # ~4.0 in Q2.14 (overflows for big inputs).
        dut.shift.reset = 0
        samples = [{"i": 30000, "q": -30000} for _ in range(n)]
        sat = []
        def watch(dut):
            for _ in range(n + 16):
                yield
            sat.append((yield dut.sat))
        run_stream(dut, samples, n, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0, extra=[watch(dut)])
        self.assertEqual(sat[0], 1)

if __name__ == "__main__":
    unittest.main()
