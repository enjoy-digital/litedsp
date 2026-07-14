#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.stream.capture import LiteDSPCapture

from test.common import column, stream_capture

class TestCapture(unittest.TestCase):
    def test_triggered_capture(self):
        depth = 16
        dut = LiteDSPCapture(depth=depth, data_width=16, with_csr=False)
        dut.threshold.reset = 5000
        # Quiet samples, then a sample crossing the threshold, then a ramp.
        quiet = [(100, 0)]*8
        burst = [(6000 + 100*k, -k) for k in range(40)]   # first sample (6000) triggers.
        data  = quiet + burst

        @passive
        def driver(dut):
            for (i, q) in data:
                yield dut.sink.i.eq(i)
                yield dut.sink.q.eq(q)
                yield dut.sink.valid.eq(1)
                yield
            yield dut.sink.valid.eq(0)
            while True:
                yield

        cap = []
        run_simulation(dut, [driver(dut),
            stream_capture(dut.source, cap, depth, ["i", "q"], ready_rate=1.0)])
        gi = column(cap, "i", 16)
        gq = column(cap, "q", 16)
        # Capture starts at the triggering sample (first burst sample = 6000).
        self.assertEqual(len(gi), depth)
        self.assertEqual(gi[0], 6000)
        self.assertEqual(gi[1], 6100)
        self.assertTrue(np.array_equal(gi, [6000 + 100*k for k in range(depth)]))
        self.assertTrue(np.array_equal(gq, [-k for k in range(depth)]))   # Q survives round trip.

class TestCaptureWishbone(unittest.TestCase):
    def test_memory_mapped_readout(self):
        depth = 8
        dut = LiteDSPCapture(depth=depth, data_width=16, with_csr=False, with_wishbone=True)
        dut.threshold.reset = 100
        data = [(1000 + k, -k) for k in range(depth + 4)]   # First sample (1000) triggers.

        @passive
        def driver(dut):
            for (i, q) in data:
                yield dut.sink.i.eq(i)
                yield dut.sink.q.eq(q)
                yield dut.sink.valid.eq(1)
                yield
            yield dut.sink.valid.eq(0)
            while True:
                yield

        words = []
        def wb_read(dut):
            while not (yield dut.done):
                yield
            for adr in range(depth):
                yield dut.bus.adr.eq(adr)
                yield dut.bus.cyc.eq(1)
                yield dut.bus.stb.eq(1)
                yield dut.bus.sel.eq(0xF)
                yield
                while not (yield dut.bus.ack):
                    yield
                words.append((yield dut.bus.dat_r))
                yield dut.bus.cyc.eq(0)
                yield dut.bus.stb.eq(0)
                yield

        run_simulation(dut, [driver(dut), wb_read(dut)])
        for k, w in enumerate(words):
            i, q = data[k]
            self.assertEqual(w, (i & 0xFFFF) | ((q & 0xFFFF) << 16))

if __name__ == "__main__":
    unittest.main()
