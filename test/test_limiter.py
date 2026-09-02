#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.motor.limiter import LiteDSPSlewLimiter

from test.common import run_stream, column
from test.models import slew_limiter_model

class TestSlewLimiter(unittest.TestCase):
    def run_limiter(self, x, rate, throttle=0.2, ready_rate=0.7, bypass=0):
        dut = LiteDSPSlewLimiter(data_width=16, with_csr=False)
        dut.rate.reset, dut.bypass.reset = rate, bypass
        cap = run_stream(dut, [{"data": int(v)} for v in x], len(x), ["data"], ["data"],
            sink_throttle=throttle, source_ready_rate=ready_rate)
        return dut, column(cap, "data", 16)

    # verify-tier: model — state advances per accepted sample; bit-exact under backpressure.
    def test_bit_exact(self):
        prng = random.Random(1)
        x = [prng.randint(-30000, 30000) for _ in range(300)]
        for rate in (500, 4000, 32767):
            with self.subTest(rate=rate):
                dut, got = self.run_limiter(x, rate)
                self.assertTrue(np.array_equal(got, slew_limiter_model(x, rate)))
                self.assertEqual(dut.latency, 1)

    # verify-tier: bound — a step of D reaches the target in exactly ceil(D/rate) samples,
    # monotonically, with no overshoot (structural: the step never crosses the input).
    def test_step_timing(self):
        D, rate = 20000, 300
        x = [D]*100 + [-D]*200
        _, got = self.run_limiter(x, rate, throttle=0.0, ready_rate=1.0)
        n_up = -(-D//rate)
        self.assertEqual(int(np.argmax(got == D)), n_up - 1)
        self.assertTrue(np.all(np.diff(got[:n_up - 1]) == rate))   # Last step = remainder.
        self.assertEqual(int(np.argmax(got[100:] == -D)), -(-2*D//rate) - 1)
        self.assertLessEqual(got.max(), D)
        self.assertGreaterEqual(got.min(), -D)

    def test_bypass(self):
        prng = random.Random(2)
        x = [prng.randint(-30000, 30000) for _ in range(120)]
        _, got = self.run_limiter(x, 10, bypass=1)
        self.assertTrue(np.array_equal(got, np.array(x)))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            LiteDSPSlewLimiter(data_width=2, with_csr=False)

if __name__ == "__main__":
    unittest.main()
