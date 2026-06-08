#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation

from litedsp.level.power import Power

from test.common import stream_driver
from test.models import power_model

class TestPower(unittest.TestCase):
    def run_power(self, x_i, x_q, window_log2, n_updates):
        n   = len(x_i)
        dut = Power(data_width=16, with_csr=False)
        dut.window_log2.reset = window_log2
        samples = [{"i": x_i[k], "q": x_q[k]} for k in range(n)]
        updates = []

        def drain_and_watch(dut):
            yield dut.source.ready.eq(1)
            while len(updates) < n_updates:
                yield
                if (yield dut.update):
                    updates.append((yield dut.power))

        run_simulation(dut, [
            stream_driver(dut.sink, samples, ["i", "q"], seed=1, throttle=0.2),
            drain_and_watch(dut),
        ])
        return updates

    def test_block_average(self):
        window_log2 = 4
        window      = 1 << window_log2
        prng        = random.Random(1)
        n           = window*8
        xi = [prng.randint(-20000, 20000) for _ in range(n)]
        xq = [prng.randint(-20000, 20000) for _ in range(n)]
        got = self.run_power(xi, xq, window_log2, n_updates=8)
        ref = power_model(xi, xq, window=window)[:len(got)]
        self.assertTrue(np.array_equal(np.array(got), ref))

    def test_constant(self):
        window_log2 = 3
        i, q = 1000, -2000
        n    = (1 << window_log2)*4
        got  = self.run_power([i]*n, [q]*n, window_log2, n_updates=4)
        self.assertTrue(all(v == i*i + q*q for v in got))

if __name__ == "__main__":
    unittest.main()
