#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.numeric import LiteDSPISqrt

from test.common import run_stream, column
from test.models import isqrt_model

class TestISqrt(unittest.TestCase):
    def test_bit_exact(self):
        dut  = LiteDSPISqrt(in_width=32, with_csr=False)
        prng = random.Random(1)
        x    = [prng.randint(0, (1 << 32) - 1) for _ in range(300)]
        cap  = run_stream(dut, [{"data": v} for v in x], len(x), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data"), isqrt_model(x)))

if __name__ == "__main__":
    unittest.main()
