#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation

from litedsp.stream.combine import Combine

from test.common import stream_driver, stream_capture, column
from test.models import combine_model

class TestCombine(unittest.TestCase):
    def run_combine(self, chans_i, chans_q, enable, data_width=16):
        n_channels = len(chans_i)
        n          = len(chans_i[0])
        dut        = Combine(n_channels=n_channels, data_width=data_width, with_csr=False)
        dut.enable.reset = enable
        captured   = []
        gens = []
        for k in range(n_channels):
            samples = [{"i": chans_i[k][j], "q": chans_q[k][j]} for j in range(n)]
            gens.append(stream_driver(dut.sinks[k], samples, ["i", "q"], seed=10+k, throttle=0.2))
        gens.append(stream_capture(dut.source, captured, n, ["i", "q"], seed=99, ready_rate=0.7))
        run_simulation(dut, gens)
        return column(captured, "i", data_width), column(captured, "q", data_width)

    def rand_channels(self, n_channels, n, seed, amp=20000):
        prng = random.Random(seed)
        ci = [[prng.randint(-amp, amp) for _ in range(n)] for _ in range(n_channels)]
        cq = [[prng.randint(-amp, amp) for _ in range(n)] for _ in range(n_channels)]
        return ci, cq

    def test_sum_all(self):
        ci, cq = self.rand_channels(4, 200, 1, amp=6000)  # 4*6000 < 32767: no saturation.
        gi, gq = self.run_combine(ci, cq, enable=0b1111)
        ri, rq = combine_model(ci, cq, enable=[1, 1, 1, 1])
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))

    def test_enable_mask(self):
        ci, cq = self.rand_channels(4, 200, 2)
        gi, gq = self.run_combine(ci, cq, enable=0b0101)
        ri, rq = combine_model(ci, cq, enable=[1, 0, 1, 0])
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))

    def test_saturation(self):
        # Large channels must saturate (and the model uses the same saturation).
        ci, cq = self.rand_channels(4, 200, 3, amp=30000)
        gi, gq = self.run_combine(ci, cq, enable=0b1111)
        ri, rq = combine_model(ci, cq, enable=[1, 1, 1, 1])
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))
        self.assertTrue((np.abs(gi) == 32767).any())  # Saturation actually exercised.

if __name__ == "__main__":
    unittest.main()
