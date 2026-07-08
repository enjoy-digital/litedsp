#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the with_irq=True EventManager support on trigger-type blocks.

Each test drives the block into its trigger condition and checks the corresponding event's
``pending`` latches (and stays clear before the condition), i.e. an IRQ would be raised.
"""

import unittest

from migen import run_simulation, passive

from litedsp.level.squelch    import Squelch
from litedsp.level.agc        import AGC
from litedsp.stream.capture   import Capture
from litedsp.analysis.detect  import EnergyDetector

@passive
def feed_iq(sink, samples):
    """Drive (i, q) tuples, then idle."""
    for (i, q) in samples:
        yield sink.i.eq(i)
        yield sink.q.eq(q)
        yield sink.valid.eq(1)
        yield
        while (yield sink.ready) == 0:
            yield
    yield sink.valid.eq(0)
    while True:
        yield

def wait_pending(ev_source, timeout=200):
    for _ in range(timeout):
        if (yield ev_source.pending):
            return
        yield
    raise AssertionError("event did not become pending")

class TestIRQ(unittest.TestCase):
    def test_squelch_open_close_events(self):
        dut = Squelch(data_width=16, with_csr=False, with_irq=True)
        dut.open_threshold.reset  = 1000
        dut.close_threshold.reset = 500
        samples = [(0, 0)]*4 + [(2000, 0)]*8 + [(0, 0)]*8   # quiet -> loud -> quiet.

        def check():
            self.assertEqual((yield dut.ev.opened.pending), 0)
            yield from wait_pending(dut.ev.opened)
            yield from wait_pending(dut.ev.closed)

        run_simulation(dut, [feed_iq(dut.sink, samples), check(), always_ready(dut.source)])

    def test_energy_detector_event(self):
        dut = EnergyDetector(data_width=16, avg_shift=2, with_csr=False, with_irq=True)
        samples = [(10, 0)]*32 + [(20000, 0)]*4             # noise -> strong signal.

        def check():
            self.assertEqual((yield dut.ev.detect.pending), 0)
            yield from wait_pending(dut.ev.detect)

        run_simulation(dut, [feed_iq(dut.sink, samples), check(), always_ready(dut.source)])

    def test_capture_done_event(self):
        dut = Capture(depth=8, data_width=16, with_csr=False, with_irq=True)
        dut.threshold.reset = 100
        samples = [(0, 0)]*4 + [(1000 + k, 0) for k in range(16)]

        def check():
            self.assertEqual((yield dut.ev.done.pending), 0)
            yield from wait_pending(dut.ev.done)

        run_simulation(dut, [feed_iq(dut.sink, samples), check()])

    def test_agc_railed_event(self):
        # Tiny gain_max + weak input: the loop integrates up and hits the clamp.
        dut = AGC(data_width=16, gain_frac=8, mu=2, gain_max=300, with_csr=False, with_irq=True)
        samples = [(10, 0)]*64

        def check():
            self.assertEqual((yield dut.ev.railed.pending), 0)
            yield from wait_pending(dut.ev.railed)

        run_simulation(dut, [feed_iq(dut.sink, samples), check(), always_ready(dut.source)])

@passive
def always_ready(source):
    yield source.ready.eq(1)
    while True:
        yield

if __name__ == "__main__":
    unittest.main()
