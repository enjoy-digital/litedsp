#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.level.clipper import LiteDSPClipper

from test.common import run_stream, column

class TestClipper(unittest.TestCase):
    def test_clamp(self):
        dut = LiteDSPClipper(data_width=16, with_csr=False)
        thr = 10000
        dut.threshold.reset = thr
        prng = random.Random(2)
        xi = [prng.randint(-32000, 32000) for _ in range(200)]
        xq = [prng.randint(-32000, 32000) for _ in range(200)]
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
            len(xi), ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        gi = column(cap, "i", 16)
        self.assertTrue(np.array_equal(gi, np.clip(xi, -thr, thr)))

if __name__ == "__main__":
    unittest.main()
