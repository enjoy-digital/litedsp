#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.level.logdb import LiteDSPLog2, LiteDSPLogPower

from test.common import run_stream, column
from test.models import log2_model

class TestLog2(unittest.TestCase):
    def test_bit_exact(self):
        dut  = LiteDSPLog2(in_width=32, frac_bits=8, with_csr=False)
        prng = random.Random(1)
        x    = [prng.randint(0, (1 << 31)) for _ in range(300)]
        cap  = run_stream(dut, [{"data": v} for v in x], len(x), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data"), log2_model(x, 32, 8)))

    def test_logpower_db(self):
        # Doubling power adds ~3 dB.
        dut = LiteDSPLogPower(in_width=32, out_frac=4, with_csr=False)
        xs  = [1 << 20, 1 << 21, 1 << 22]
        cap = run_stream(dut, [{"data": v} for v in xs], len(xs), ["data"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        db = column(cap, "data")/16.0
        self.assertAlmostEqual(db[1] - db[0], 3.01, delta=0.3)
        self.assertAlmostEqual(db[2] - db[1], 3.01, delta=0.3)

if __name__ == "__main__":
    unittest.main()
