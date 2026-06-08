#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.level.saturate import Saturate

from test.common import run_stream, column, np_scaled

class TestSaturate(unittest.TestCase):
    def run_sat(self, x_i, x_q, in_width, out_width, shift):
        n   = len(x_i)
        dut = Saturate(data_width=out_width, in_width=in_width, shift=shift, with_csr=False)
        samples  = [{"i": x_i[k], "q": x_q[k]} for k in range(n)]
        captured = run_stream(dut, samples, n, ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        return column(captured, "i", out_width), column(captured, "q", out_width)

    def test_rescale_round_saturate(self):
        # 32-bit intermediates rescaled to 16-bit: must round and clamp like np_scaled.
        prng = random.Random(1)
        xi = [prng.randint(-(1 << 28), (1 << 28)) for _ in range(200)]
        xq = [prng.randint(-(1 << 28), (1 << 28)) for _ in range(200)]
        gi, gq = self.run_sat(xi, xq, in_width=32, out_width=16, shift=15)
        ri = np_scaled(xi, 15, 16)
        rq = np_scaled(xq, 15, 16)
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))

    def test_passthrough(self):
        prng = random.Random(2)
        xi = [prng.randint(-30000, 30000) for _ in range(128)]
        xq = [prng.randint(-30000, 30000) for _ in range(128)]
        gi, gq = self.run_sat(xi, xq, in_width=16, out_width=16, shift=0)
        self.assertTrue(np.array_equal(gi, np.array(xi)))
        self.assertTrue(np.array_equal(gq, np.array(xq)))

if __name__ == "__main__":
    unittest.main()
