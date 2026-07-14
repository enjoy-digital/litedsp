#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation

from litedsp.stream.split import LiteDSPSplit

from test.common import column, stream_driver, stream_capture

class TestSplit(unittest.TestCase):
    def test_duplicate(self):
        dut = LiteDSPSplit(n=3, data_width=16)
        prng = random.Random(3)
        xi = [prng.randint(-1000, 1000) for _ in range(60)]
        xq = [prng.randint(-1000, 1000) for _ in range(60)]
        caps = [[] for _ in range(3)]
        run_simulation(dut, [
            stream_driver(dut.sink, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
                ["i", "q"], throttle=0.1),
            *[stream_capture(dut.sources[j], caps[j], len(xi), ["i", "q"], seed=j, ready_rate=0.6 + 0.1*j)
              for j in range(3)],
        ])
        for j in range(3):
            self.assertTrue(np.array_equal(column(caps[j], "i", 16), xi))

if __name__ == "__main__":
    unittest.main()
