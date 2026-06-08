#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.analysis.magnitude import Magnitude
from litedsp.stream.buffer      import SkidBuffer

from test.common import run_stream, column

class TestMagnitudeExact(unittest.TestCase):
    def test_cordic_accuracy(self):
        dut = Magnitude(data_width=16, method="cordic", with_csr=False)
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

class TestSkidBuffer(unittest.TestCase):
    def test_passthrough(self):
        dut = SkidBuffer(data_width=16)
        prng = random.Random(2)
        data = [{"i": prng.randint(-9000, 9000), "q": prng.randint(-9000, 9000)} for _ in range(120)]
        cap = run_stream(dut, data, len(data), ["i", "q"], ["i", "q"],
            sink_throttle=0.3, source_ready_rate=0.6)
        self.assertTrue(np.array_equal(column(cap, "i", 16), [d["i"] for d in data]))
        self.assertTrue(np.array_equal(column(cap, "q", 16), [d["q"] for d in data]))

if __name__ == "__main__":
    unittest.main()
