#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.stream.route import LiteDSPChannelMux, LiteDSPTDMMux, LiteDSPTDMDemux

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

class TestTDMMuxDemux(unittest.TestCase):
    # verify-tier: model — strict round-robin interleave: beat k of the frame comes from sink k
    # tagged channel k, independently throttled inputs; the demux routes by tag.
    def test_mux_round_robin(self):
        prng = random.Random(1)
        n, frames = 3, 80
        chans = [[prng.randint(-2**23, 2**23 - 1) for _ in range(frames)] for _ in range(n)]
        dut = LiteDSPTDMMux(n_channels=n, data_width=24, with_csr=False)
        captured = []
        run_simulation(dut, [
            *[stream_driver(dut.sinks[c], [{"data": v} for v in chans[c]], ["data"], seed=c,
                            throttle=0.3)
              for c in range(n)],
            stream_capture(dut.source, captured, n*frames, ["data", "channel"], seed=9,
                           ready_rate=0.7),
        ])
        got_data = column(captured, "data", 24).tolist()
        got_ch   = column(captured, "channel").tolist()
        self.assertEqual(got_ch, [k % n for k in range(n*frames)])
        self.assertEqual(got_data, [chans[k % n][k//n] for k in range(n*frames)])
        self.assertEqual(dut.latency, 0)

    def test_demux_by_tag(self):
        prng = random.Random(2)
        n, frames = 2, 60
        beats = [{"data": prng.randint(-2**23, 2**23 - 1), "channel": k % n}
                                       for k in range(n*frames)]
        dut = LiteDSPTDMDemux(n_channels=n, data_width=24, with_csr=False)
        caps = [[] for _ in range(n)]
        run_simulation(dut, [
            stream_driver(dut.sink, beats, ["data", "channel"], seed=1, throttle=0.2),
            *[stream_capture(dut.sources[c], caps[c], frames, ["data"], seed=3 + c, ready_rate=0.6)
              for c in range(n)],
        ])
        for c in range(n):
            self.assertEqual(column(caps[c], "data", 24).tolist(),
                             [b["data"] for b in beats if b["channel"] == c])

    def test_mono_passthrough(self):
        beats = [{"data": k*1000 - 30000} for k in range(50)]
        mux   = LiteDSPTDMMux(n_channels=1, data_width=24, with_csr=False)
        cap   = []
        run_simulation(mux, [
            stream_driver(mux.sinks[0], beats, ["data"], seed=1, throttle=0.2),
            stream_capture(mux.source, cap, len(beats), ["data"], seed=2, ready_rate=0.7),
        ])
        self.assertEqual(column(cap, "data", 24).tolist(), [b["data"] for b in beats])

    def test_invalid(self):
        with self.assertRaises(ValueError):
            LiteDSPTDMMux(n_channels=0, with_csr=False)
        with self.assertRaises(ValueError):
            LiteDSPTDMDemux(n_channels=0, with_csr=False)

if __name__ == "__main__":
    unittest.main()
