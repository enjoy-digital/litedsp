#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.stream.route import LiteDSPChannelMux

from test.common import column, stream_driver, stream_capture

class TestRoute(unittest.TestCase):
    def test_mux_demux(self):
        dut = LiteDSPChannelMux(n=3, data_width=16, with_csr=False)
        dut.sel.reset = 1
        caps = []
        prng = random.Random(1)
        data = [{"i": prng.randint(-1000, 1000), "q": prng.randint(-1000, 1000)} for _ in range(40)]

        @passive
        def feed_others(dut):
            yield dut.sinks[0].valid.eq(0)
            yield dut.sinks[2].valid.eq(0)
            while True:
                yield
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sinks[1], data, ["i", "q"], throttle=0.1),
            feed_others(dut),
            stream_capture(dut.source, cap, len(data), ["i", "q"], ready_rate=0.8),
        ])
        self.assertTrue(np.array_equal(column(cap, "i", 16), [d["i"] for d in data]))

if __name__ == "__main__":
    unittest.main()
