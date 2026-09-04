#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import *

from litedsp.radar.timing   import LiteDSPPulseGenerator
from litedsp.radar.waveform import chirp_words

from test.common import run_stream, column
from test.models import pulse_generator_model

OUT = ["i", "q", "first", "last"]

class TestPulseGenerator(unittest.TestCase):
    # verify-tier: model — two PRIs of 48 samples with a 16-sample chirp under a throttled source:
    # bit-exact against chirp_reference (framing, zeros), pulse_start / pulse_count and tx.
    def test_bit_exact(self):
        dut = LiteDSPPulseGenerator(pulse_len=16, bandwidth=0.5, pri=48, n_pulses=2, with_csr=False)
        dut.enable.reset = 1
        self.starts = 0
        cap = run_stream(dut, None, 2*48, [], OUT, source_ready_rate=0.7,
                         extra=[self._monitor(dut)])
        ref = pulse_generator_model(2, 16, 48, 0.5)
        for name, col, w in zip(OUT, ref, (16, 16, None, None)):
            self.assertEqual(column(cap, name, w).tolist(), col.tolist(), name)
        self.assertGreaterEqual(self.starts, 2)
        self.assertGreaterEqual(self.count, 2)

    # verify-tier: bound — single mode: one pulse (chirp + zeros to the PRI) per trigger and
    # nothing more; runtime pulse_len / start / rate words from chirp_words give a 24-sample
    # chirp of bandwidth 0.25 bit-exact.
    def test_single_and_runtime_words(self):
        dut = LiteDSPPulseGenerator(pulse_len=16, bandwidth=0.5, pri=40, n_pulses=4, with_csr=False)
        dut.single.reset = 1
        start, rate = chirp_words(0.25, 24)
        dut.start.reset, dut.rate.reset, dut.pulse_len.reset = start, rate, 24
        cap = run_stream(dut, None, 40, [], OUT, source_ready_rate=1.0,
                         extra=[self._trigger(dut, at=3)])
        ref = pulse_generator_model(1, 24, 40, 0.25)
        for name, col, w in zip(OUT, ref, (16, 16, None, None)):
            self.assertEqual(column(cap, name, w).tolist(), col.tolist(), name)
        self.assertEqual(self.count, 1)
        self.assertEqual(self.running, 0)
        for kwargs in ({"pulse_len": 128}, {"pri": 1 << 24}, {"n_pulses": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPPulseGenerator(with_csr=False, **kwargs)

    def _monitor(self, dut):
        @passive
        def gen():
            while True:
                self.starts += (yield dut.pulse_start)
                self.count   = (yield dut.pulse_count)
                self.running = (yield dut.running)
                yield
        return gen()

    def _trigger(self, dut, at):
        @passive
        def gen():
            for _ in range(at):
                yield
            yield dut.trigger.eq(1)
            yield
            yield dut.trigger.eq(0)
            while True:
                self.count   = (yield dut.pulse_count)
                self.running = (yield dut.running)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
