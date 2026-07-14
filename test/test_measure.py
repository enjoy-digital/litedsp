#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.analysis.stats     import LiteDSPStats
from litedsp.analysis.histogram import LiteDSPHistogram
from litedsp.analysis.peak_bin  import LiteDSPPeakBin

from test.common import run_stream, column, stream_capture, to_signed

class TestStats(unittest.TestCase):
    def test_window(self):
        w = 6
        N = 1 << w
        dut = LiteDSPStats(data_width=16, window_log2=w, with_csr=False)
        prng = random.Random(1)
        x = [prng.randint(-20000, 20000) for _ in range(N)]
        cap = run_stream(dut, [{"data": v} for v in x], 1,
            ["data"], ["min", "max", "mean", "variance"],
            sink_throttle=0.0, source_ready_rate=1.0)
        s = sum(x); sq = sum(v*v for v in x)
        self.assertEqual(to_signed(column(cap, "min"), 16)[0], min(x))
        self.assertEqual(to_signed(column(cap, "max"), 16)[0], max(x))
        self.assertEqual(to_signed(column(cap, "mean"), 16)[0], s >> w)
        self.assertEqual(column(cap, "variance")[0], (sq >> w) - (s >> w)**2)

class TestHistogram(unittest.TestCase):
    def test_counts(self):
        bits, w = 4, 8
        B, N = 1 << bits, 1 << 8
        dut = LiteDSPHistogram(data_width=16, bits=bits, window_log2=w, with_csr=False)
        prng = random.Random(2)
        x = [prng.randint(-32768, 32767) for _ in range(N)]
        cap = run_stream(dut, [{"data": v} for v in x], B, ["data"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        got = column(cap, "data")
        idx = [((v + 32768) >> (16 - bits)) for v in x]
        exp = np.bincount(idx, minlength=B)
        self.assertTrue(np.array_equal(got, exp))

class TestPeakBin(unittest.TestCase):
    def test_argmax(self):
        dut = LiteDSPPeakBin(data_width=32, index_width=8, with_csr=False)
        frames = [[10, 50, 30, 200, 40, 5, 7, 8],
                  [3, 3, 3, 3, 9, 3, 3, 3]]

        @passive
        def driver(ep):
            for frame in frames:
                for k, v in enumerate(frame):
                    yield ep.data.eq(v)
                    yield ep.first.eq(int(k == 0))
                    yield ep.last.eq(int(k == len(frame) - 1))
                    yield ep.valid.eq(1)
                    yield
                    while (yield ep.ready) == 0:
                        yield
                yield ep.valid.eq(0)

        cap = []
        run_simulation(dut, [driver(dut.sink),
            stream_capture(dut.source, cap, 2, ["index", "value"], ready_rate=1.0)])
        self.assertEqual(list(column(cap, "index")), [3, 4])
        self.assertEqual(list(column(cap, "value")), [200, 9])

if __name__ == "__main__":
    unittest.main()
