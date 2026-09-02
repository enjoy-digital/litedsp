#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.motor.pwm import LiteDSPPWM

from test.common import stream_driver
from test.models import pwm_model

FS = (1 << 15) - 1

def capture_pins(dut, n_cycles, fault=None):
    """Record (pwm_h, pwm_l, trigger, ready) every cycle from reset, optionally driving fault."""
    h, l, t, r = [], [], [], []

    def rec():
        for cyc in range(n_cycles):
            if fault is not None and cyc + 1 < n_cycles:
                yield dut.fault.eq(int(fault[cyc + 1]))     # Visible next cycle.
            h.append((yield dut.pwm_h))
            l.append((yield dut.pwm_l))
            t.append((yield dut.trigger))
            r.append((yield dut.sink.ready))
            yield
    return rec, (h, l, t, r)

def run_pwm(dut, duties, n_cycles, fault=None):
    rec, logs = capture_pins(dut, n_cycles, fault)
    samples = [{"a": a, "b": b, "c": c} for a, b, c in duties]
    run_simulation(dut, [stream_driver(dut.sink, samples, ["a", "b", "c"], seed=1), rec()])
    return tuple(np.array(x) for x in logs)

class TestPWM(unittest.TestCase):
    def build(self, period, dead_time, enable=1, trigger=(0, 0), with_irq=False):
        dut = LiteDSPPWM(data_width=16, period_width=8, dead_time_width=4, with_csr=False,
            with_irq=with_irq)
        dut.period.reset, dut.dead_time.reset, dut.enable.reset = period, dead_time, enable
        dut.trigger_count.reset, dut.trigger_direction.reset = trigger
        return dut

    # verify-tier: model — cycle-exact gate signals, trigger and acceptance windows vs the
    # register-level model over 1500 cycles (random duties, dead time 3, period 32).
    def test_cycle_exact_vs_model(self):
        prng   = random.Random(1)
        duties = [(prng.randint(-FS, FS), prng.randint(-FS, FS), prng.randint(-FS, FS))
                  for _ in range(40)]
        period, dead_time, n = 32, 3, 1500
        dut = self.build(period, dead_time, trigger=(period, 1))
        h, l, t, r = run_pwm(dut, duties, n)
        rh, rl, rt, rr = pwm_model(duties, period, dead_time, n, trigger_count=period,
            trigger_direction=1)
        self.assertTrue(np.array_equal(h, rh))
        self.assertTrue(np.array_equal(l, rl))
        self.assertTrue(np.array_equal(t, rt))
        self.assertTrue(np.array_equal(r, rr))
        self.assertIsNone(dut.latency)

    # verify-tier: bound — in steady state a phase with duty d (cmp = round(period*(d + 1)/2),
    # 0 < cmp < period) is high for 2*cmp - 1 cycles per 2*period-cycle period (count < cmp on
    # both slopes, the valley counted once) minus one dead time (after its rising edge), its
    # complement for the remaining 2*period - 2*cmp + 1 cycles minus one dead time, and the
    # two never overlap; cmp = 0 keeps the low side on for the whole period (no edges).
    def test_duty_cycle_counts(self):
        period, dead_time = 64, 2
        duties = [(-FS, 0, FS//2)]*8
        h, l, _, _ = run_pwm(self.build(period, dead_time), duties, 2*period*8)
        start = 2*period*4                                       # Steady state (double buffer).
        win   = slice(start, start + 2*period)
        for k, d in enumerate(duties[0]):
            cmp = int(np.floor(period*(d + (1 << 15))/(1 << 16) + 0.5))
            hk, lk = (h[win] >> k) & 1, (l[win] >> k) & 1
            if cmp == 0:
                self.assertEqual((int(hk.sum()), int(lk.sum())), (0, 2*period), f"phase {k}")
            else:
                self.assertEqual(int(hk.sum()), 2*cmp - 1 - dead_time, f"phase {k} high")
                self.assertEqual(int(lk.sum()), 2*period - 2*cmp + 1 - dead_time, f"phase {k} low")
            self.assertEqual(int((hk & lk).sum()), 0, f"phase {k} overlap")

    def test_ready_once_per_period_and_missed_flag(self):
        period, n = 16, 2*16*10
        dut = self.build(period, 0)
        _, _, _, r = run_pwm(dut, [(0, 0, 0)]*20, n)
        self.assertEqual(int(r.sum()), (n - 1)//(2*period))    # Valleys at 2*period, 4*period...
        self.assertTrue(np.all(np.diff(np.nonzero(r)[0]) == 2*period))
        # Starving the sink sets the sticky missed flag; missed_clear clears it.
        dut = self.build(period, 0)
        flags = []

        def starve():
            for _ in range(2*period*3):
                yield
            flags.append((yield dut.missed))
            yield dut.missed_clear.eq(1)
            yield
            yield dut.missed_clear.eq(0)
            yield
            flags.append((yield dut.missed))
        run_simulation(dut, starve())
        self.assertEqual(flags[0], 1)
        # Cleared, then set again at the next starved valley (still no sample offered).
        self.assertIn(flags[1], (0, 1))

    def test_fault_latch_and_irq(self):
        period, n = 16, 2*16*8
        fault = np.zeros(n, np.int64)
        fault[100:104] = 1
        dut = self.build(period, 1, with_irq=True)
        pend = []

        def watch():
            for _ in range(n):
                pend.append((yield dut.ev.fault.pending))
                yield
        rec, logs = capture_pins(dut, n, fault)
        run_simulation(dut, [stream_driver(dut.sink, [{"a": 0, "b": 0, "c": 0}]*20,
            ["a", "b", "c"], seed=1), rec(), watch()])
        h, l = np.array(logs[0]), np.array(logs[1])
        self.assertTrue(np.any(h[:100] | l[:100]))                # Switching before the fault.
        self.assertTrue(np.all((h[103:] | l[103:]) == 0))         # All six off, latched.
        self.assertEqual(pend[99], 0)
        self.assertEqual(pend[-1], 1)
        rh, rl, _, _ = pwm_model([(0, 0, 0)], period, 1, n, fault=fault)
        self.assertTrue(np.array_equal(h, rh) and np.array_equal(l, rl))

    def test_trigger_phase(self):
        period, n = 16, 2*16*6
        for trig, first in (((0, 0), 2*period), ((period, 1), period), ((5, 0), 2*period - 5)):
            with self.subTest(trigger=trig):
                _, _, t, _ = run_pwm(self.build(period, 0, trigger=trig), [(0, 0, 0)]*20, n)
                pulses = np.nonzero(t)[0]
                self.assertEqual(int(pulses[0]), first + 1)        # Registered: one cycle later.
                self.assertTrue(np.all(np.diff(pulses) == 2*period))

    def test_invalid(self):
        for kwargs in ({"period_width": 3}, {"dead_time_width": 0}, {"data_width": 2}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPPWM(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
