#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.radar.timing import LiteDSPRangeGate

from test.common import run_stream, stream_driver, stream_capture, column
from test.models import range_gate_model

def beats(prng, n):
    return [{"i": prng.randint(-30000, 30000), "q": prng.randint(-30000, 30000)} for _ in range(n)]

class TestRangeGate(unittest.TestCase):
    # verify-tier: model — sample-domain PRI timer: gated, framed pulses bit-exact under
    # backpressure (pri 24, gate 4..11, 3 pulses per CPI), continuous mode.
    def test_bit_exact_continuous(self):
        prng = random.Random(1)
        x    = beats(prng, 300)
        dut  = LiteDSPRangeGate(data_width=16, n_range_bins=8, n_pulses=3, pri=24, gate_start=4,
                                with_csr=False)
        dut.enable.reset = 1
        ri, rq, rf, rl = range_gate_model([b["i"] for b in x], [b["q"] for b in x], 24, 4, 8, 3)
        cap = run_stream(dut, x, len(ri), ["i", "q"], ["i", "q", "first", "last"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertEqual(len(ri), 13*8)                       # 300 samples: 12 PRIs + a gated tail.
        self.assertTrue(np.array_equal(column(cap, "i", 16), ri))
        self.assertTrue(np.array_equal(column(cap, "q", 16), rq))
        self.assertEqual(column(cap, "first").tolist(), rf.tolist())
        self.assertEqual(column(cap, "last").tolist(), rl.tolist())
        self.assertEqual(dut.latency, 1)

    # verify-tier: bound — single mode emits exactly one CPI (n_pulses x gate_len beats) per
    # trigger, then nothing; the CPI IRQ pends once per trigger.
    def test_single_trigger(self):
        prng = random.Random(2)
        x    = beats(prng, 260)
        dut  = LiteDSPRangeGate(data_width=16, n_range_bins=8, n_pulses=3, pri=24, gate_start=2,
            with_csr=False, with_irq=True)
        dut.single.reset = 1
        trig = [int(k in (5, 150)) for k in range(260)]
        ri, rq, rf, rl = range_gate_model([b["i"] for b in x], [b["q"] for b in x], 24, 2, 8, 3,
            enable=0, single=1, trigger=np.array(trig))
        self.assertEqual(len(ri), 2*3*8)
        captured, seen = [], {}
        def driver():
            for k, b in enumerate(x):
                yield dut.trigger.eq(trig[k])
                yield dut.sink.i.eq(b["i"]); yield dut.sink.q.eq(b["q"]); yield dut.sink.valid.eq(1)
                yield
                while (yield dut.sink.ready) == 0:
                    yield
            yield dut.sink.valid.eq(0)
            yield dut.trigger.eq(0)
            for _ in range(8):
                yield
            seen["irq"]   = (yield dut.ev.cpi.pending)
            seen["count"] = (yield dut.pulse_count)
            seen["run"]   = (yield dut.running)
        run_simulation(dut, [
            driver(), stream_capture(dut.source, captured, len(ri), ["i", "q", "first", "last"],
            seed=3, ready_rate=0.7)])
        self.assertTrue(np.array_equal(column(captured, "i", 16), ri))
        self.assertEqual(column(captured, "first").tolist(), rf.tolist())
        self.assertEqual(column(captured, "last").tolist(), rl.tolist())
        self.assertEqual((seen["irq"], seen["count"], seen["run"]), (1, 6, 0))

    def test_invalid(self):
        for kwargs in ({"n_range_bins": 0}, {"gate_start": 100}, {"pri": 1}, {"pulse_width": 200},
                       {"n_pulses": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPRangeGate(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
