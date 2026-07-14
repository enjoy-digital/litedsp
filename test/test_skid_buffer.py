#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.stream.buffer import LiteDSPSkidBuffer

from test.common import run_stream, column

class TestSkidBuffer(unittest.TestCase):
    def test_passthrough(self):
        dut = LiteDSPSkidBuffer(data_width=16)
        prng = random.Random(2)
        data = [{"i": prng.randint(-9000, 9000), "q": prng.randint(-9000, 9000)} for _ in range(120)]
        cap = run_stream(dut, data, len(data), ["i", "q"], ["i", "q"],
            sink_throttle=0.3, source_ready_rate=0.6)
        self.assertTrue(np.array_equal(column(cap, "i", 16), [d["i"] for d in data]))
        self.assertTrue(np.array_equal(column(cap, "q", 16), [d["q"] for d in data]))

if __name__ == "__main__":
    unittest.main()
