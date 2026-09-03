#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.radar.corner_turn import LiteDSPCornerTurn

from test.common import run_stream, stream_driver, stream_capture, column
from test.models import corner_turn_model

def cpi_beats(prng, n_bins, n_pulses, n_cpi):
    n = n_bins*n_pulses*n_cpi
    return [{"i": prng.randint(-30000, 30000), "q": prng.randint(-30000, 30000),
             "first": int(k % n_bins == 0), "last": int(k % n_bins == n_bins - 1)} for k in range(n)]

class TestCornerTurn(unittest.TestCase):
    # verify-tier: model — two CPIs of 8 range bins x 16 pulses transposed bit-exactly under
    # backpressure, output framed per range-bin column.
    def test_bit_exact(self):
        prng  = random.Random(1)
        beats = cpi_beats(prng, 8, 16, 2)
        dut   = LiteDSPCornerTurn(n_range_bins=8, n_pulses=16, with_csr=False)
        cap   = run_stream(dut, beats, len(beats), ["i", "q", "first", "last"], ["i", "q", "first", "last"],
            sink_throttle=0.2, source_ready_rate=0.7)
        ri, rq, rf, rl = corner_turn_model([b["i"] for b in beats], [b["q"] for b in beats], 8, 16)
        self.assertTrue(np.array_equal(column(cap, "i", 16), ri))
        self.assertTrue(np.array_equal(column(cap, "q", 16), rq))
        self.assertEqual(column(cap, "first").tolist(), rf.tolist())
        self.assertEqual(column(cap, "last").tolist(), rl.tolist())
        self.assertIsNone(dut.latency)

    # verify-tier: bound — once the first CPI has filled, the stream flows one sample per cycle
    # (no gaps) with a free-running source; a misplaced frame tag sets the sticky error.
    def test_throughput_and_frame_error(self):
        prng  = random.Random(2)
        beats = cpi_beats(prng, 8, 4, 3)
        beats[41]["first"] = 1                                          # Mid-column tag in CPI 2.
        dut   = LiteDSPCornerTurn(n_range_bins=8, n_pulses=4, with_csr=False)
        captured, times, seen = [], [], {}
        @passive
        def stamps():
            cyc = 0
            while True:
                if (yield dut.source.valid) and (yield dut.source.ready):
                    times.append(cyc)
                cyc += 1
                yield
        def driver():
            yield from stream_driver(dut.sink, beats, ["i", "q", "first", "last"], seed=1, throttle=0.0)
        def finish():
            yield from stream_capture(dut.source, captured, len(beats), ["i", "q"], seed=2, ready_rate=1.0)
            seen["frame_error"] = (yield dut.frame_error)
            yield dut.clear.eq(1)
            yield
            yield dut.clear.eq(0)
            yield
            seen["cleared"] = (yield dut.frame_error)
        run_simulation(dut, [driver(), finish(), stamps()])
        gaps = np.diff(times[32:])                                      # Steady state after CPI 0.
        self.assertEqual(int(np.max(gaps)), 1)
        self.assertEqual((seen["frame_error"], seen["cleared"]), (1, 0))

    def test_invalid(self):
        for kwargs in ({"n_range_bins": 1}, {"n_pulses": 1}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPCornerTurn(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
