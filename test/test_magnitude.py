#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.analysis.magnitude import LiteDSPMagnitude

from test.common import run_stream, column
from test.models import magnitude_model

class TestMagnitude(unittest.TestCase):
    def run_mag(self, xi, xq, beta_shift=2, data_width=16):
        dut = LiteDSPMagnitude(data_width=data_width, beta_shift=beta_shift, with_csr=False)
        samples  = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
        captured = run_stream(dut, samples, len(xi), ["i", "q"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        return column(captured, "data")

    def test_bit_exact(self):
        prng = random.Random(1)
        xi = [prng.randint(-32768, 32767) for _ in range(300)]
        xq = [prng.randint(-32768, 32767) for _ in range(300)]
        got = self.run_mag(xi, xq)
        ref = magnitude_model(xi, xq)
        self.assertTrue(np.array_equal(got, ref))

    def test_accuracy_vs_true(self):
        # alpha-max-beta-min error should stay within ~12% of the true magnitude.
        prng = random.Random(2)
        xi = [prng.randint(-32000, 32000) for _ in range(500)]
        xq = [prng.randint(-32000, 32000) for _ in range(500)]
        got  = self.run_mag(xi, xq).astype(float)
        true = np.hypot(xi, xq)
        big  = true > 2000  # Ignore tiny vectors (quantization-dominated).
        rel  = (got[big] - true[big])/true[big]
        # alpha-max-beta-min(1, 1/4): error range ~ [-11.6% @45deg, +3.1% @14deg].
        self.assertGreater(rel.min(), -0.13)
        self.assertLess(rel.max(), 0.04)

class TestMagnitudeExact(unittest.TestCase):
    def test_cordic_accuracy(self):
        dut = LiteDSPMagnitude(data_width=16, method="cordic", with_csr=False)
        prng = random.Random(1)
        xi = [prng.randint(-30000, 30000) for _ in range(300)]
        xq = [prng.randint(-30000, 30000) for _ in range(300)]
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))], len(xi),
            ["i", "q"], ["data"], sink_throttle=0.2, source_ready_rate=0.7)
        got  = column(cap, "data").astype(float)
        true = np.hypot(xi, xq)
        big  = true > 2000
        rel  = (got[big] - true[big])/true[big]
        self.assertLess(np.abs(rel).max(), 0.01)        # CORDIC: ~exact, <1%.

if __name__ == "__main__":
    unittest.main()
