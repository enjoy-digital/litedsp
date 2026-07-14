#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.stream.delay import LiteDSPDelay

from test.common import run_stream, column

class TestDelay(unittest.TestCase):
    def test_aligns(self):
        depth = 5
        dut = LiteDSPDelay(depth=depth, data_width=16)
        prng = random.Random(4)
        xi = [prng.randint(-1000, 1000) for _ in range(80)]
        cap = run_stream(dut, [{"i": xi[k], "q": 0} for k in range(len(xi))], len(xi) - depth,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        gi = column(cap, "i", 16)
        self.assertTrue(np.array_equal(gi, np.array(xi[:len(gi)])))  # No bubbles -> pure delay.

if __name__ == "__main__":
    unittest.main()
