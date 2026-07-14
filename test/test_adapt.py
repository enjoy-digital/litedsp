#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.stream.adapt import LiteDSPIQClockDomainCrossing

from test.common import run_stream, column

class TestCDC(unittest.TestCase):
    def test_same_domain_passthrough(self):
        dut = LiteDSPIQClockDomainCrossing(cd_from="sys", cd_to="sys", data_width=16, depth=8)
        prng = random.Random(2)
        data = [{"i": prng.randint(-2000, 2000), "q": prng.randint(-2000, 2000)} for _ in range(60)]
        cap = run_stream(dut, data, len(data), ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "i", 16), [d["i"] for d in data]))

if __name__ == "__main__":
    unittest.main()
