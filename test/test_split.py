#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation

from litex.gen import LiteXModule

from litedsp.stream.split import LiteDSPSplit
from litedsp.mixing.mixer import LiteDSPMixer

from test.common import column, stream_driver, stream_capture

class TestSplit(unittest.TestCase):
    def test_duplicate(self):
        dut = LiteDSPSplit(n=3, data_width=16)
        prng = random.Random(3)
        xi = [prng.randint(-1000, 1000) for _ in range(60)]
        xq = [prng.randint(-1000, 1000) for _ in range(60)]
        caps = [[] for _ in range(3)]
        run_simulation(dut, [
            stream_driver(dut.sink, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
                ["i", "q"], throttle=0.1),
            *[stream_capture(dut.sources[j], caps[j], len(xi), ["i", "q"], seed=j,
                             ready_rate=0.6 + 0.1*j)
              for j in range(3)],
        ])
        for j in range(3):
            self.assertTrue(np.array_equal(column(caps[j], "i", 16), xi))

    def count_transfers(self, top, sink, source, n_cycles=40):
        counts = {"in": 0, "out": 0}
        def gen():
            yield sink.valid.eq(1)
            yield sink.i.eq(1000)
            yield source.ready.eq(1)
            for _ in range(n_cycles):
                yield
                counts["in"]  += (yield sink.valid) & (yield sink.ready)
                counts["out"] += (yield source.valid) & (yield source.ready)
        run_simulation(top, gen())
        return counts

    def test_ready_after_valid_consumer(self):
        # A consumer that waits for valid before raising ready (AXI-legal) must not stall the
        # split: source valid may not depend on any source ready.
        class Top(LiteXModule):
            def __init__(self):
                self.split = split = LiteDSPSplit(n=2)
                self.comb += split.sources[0].ready.eq(split.sources[0].valid)
        top = Top()
        counts = self.count_transfers(top, top.split.sink, top.split.sources[1])
        self.assertEqual(counts["in"], 40)  # One sample per clock.
        self.assertEqual(counts["out"], 40)

    def test_rejoined_branches(self):
        # Both split outputs into the two inputs of a mixer (x * conj(x)): the mixer's sink
        # ready depends on its other sink valid, which must not loop back through the split.
        class Top(LiteXModule):
            def __init__(self):
                self.split = LiteDSPSplit(n=2)
                self.mixer = LiteDSPMixer(with_csr=False)
                self.comb += [
                    self.split.sources[0].connect(self.mixer.sink_a),
                    self.split.sources[1].connect(self.mixer.sink_b),
                ]
        top = Top()
        counts = self.count_transfers(top, top.split.sink, top.mixer.source)
        self.assertEqual(counts["in"], 40)
        self.assertEqual(counts["out"], 40 - top.mixer.latency)

if __name__ == "__main__":
    unittest.main()
