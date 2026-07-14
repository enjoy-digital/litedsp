#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation

from litedsp.stream.ops import LiteDSPConjugate, LiteDSPSwapIQ, LiteDSPNegate, LiteDSPIQAdd

from test.common import run_stream, column, stream_driver, stream_capture, np_saturated

class TestStreamOps(unittest.TestCase):
    def run_op(self, cls, xi, xq):
        dut = cls(data_width=16)
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))], len(xi),
            ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        return column(cap, "i", 16), column(cap, "q", 16)

    def test_ops(self):
        prng = random.Random(2)
        xi = [prng.randint(-30000, 30000) for _ in range(100)]
        xq = [prng.randint(-30000, 30000) for _ in range(100)]
        gi, gq = self.run_op(LiteDSPConjugate, xi, xq)
        self.assertTrue(np.array_equal(gi, xi) and np.array_equal(gq, -np.array(xq)))
        gi, gq = self.run_op(LiteDSPSwapIQ, xi, xq)
        self.assertTrue(np.array_equal(gi, xq) and np.array_equal(gq, xi))
        gi, gq = self.run_op(LiteDSPNegate, xi, xq)
        self.assertTrue(np.array_equal(gi, -np.array(xi)) and np.array_equal(gq, -np.array(xq)))

class TestIQAdd(unittest.TestCase):
    def test_sum_saturated(self):
        dut  = LiteDSPIQAdd(data_width=16)
        prng = random.Random(4)
        n    = 100
        a = [(prng.randint(-30000, 30000), prng.randint(-30000, 30000)) for _ in range(n)]
        b = [(prng.randint(-30000, 30000), prng.randint(-30000, 30000)) for _ in range(n)]
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink_a, [{"i": i, "q": q} for (i, q) in a], ("i", "q"), throttle=0.2),
            stream_driver(dut.sink_b, [{"i": i, "q": q} for (i, q) in b], ("i", "q"), throttle=0.3,
                seed=5),
            stream_capture(dut.source, cap, n, ("i", "q"), ready_rate=0.7),
        ])
        gi, gq = column(cap, "i", 16), column(cap, "q", 16)
        ei = np_saturated(np.array([x[0] for x in a]) + np.array([x[0] for x in b]), 16)
        eq = np_saturated(np.array([x[1] for x in a]) + np.array([x[1] for x in b]), 16)
        self.assertTrue(np.array_equal(gi, ei))
        self.assertTrue(np.array_equal(gq, eq))

if __name__ == "__main__":
    unittest.main()
