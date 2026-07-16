#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.level.agc import LiteDSPAGC

from test.common import run_stream, column
from test.models import agc_model

def tone(n, f, amp):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

class TestAGC(unittest.TestCase):
    def run_agc(self, xi, xq, target, mu, throttle=0.0, ready_rate=1.0,
                delayed_feedback=False):
        dut = LiteDSPAGC(data_width=16, gain_frac=8, mu=mu, with_csr=False,
            delayed_feedback=delayed_feedback)
        dut.target.reset = target
        cap = run_stream(dut, [{"i": a, "q": b} for a, b in zip(xi, xq)],
            len(xi), ["i", "q"], ["i", "q"], sink_throttle=throttle, source_ready_rate=ready_rate)
        return column(cap, "i", 16), column(cap, "q", 16)

    # verify-tier: model — the AGC loop is pure fixed-point arithmetic (alpha-max-beta-min
    # magnitude, error >> mu integrator, clamped gain), so the whole trajectory is bit-exact
    # against test.models.agc_model.
    def test_converges(self):
        n = 6000
        target = 8000
        x  = tone(n, 0.02, 1500)                             # weak input.
        xi = [int(round(v.real)) for v in x]
        xq = [int(round(v.imag)) for v in x]
        gi, gq = self.run_agc(xi, xq, target, mu=6)
        mi, mq = agc_model(xi, xq, target, gain_frac=8, mu=6)
        np.testing.assert_array_equal(gi, mi)
        np.testing.assert_array_equal(gq, mq)
        # Functional: steady-state |output| sits at the target.
        y = gi + 1j*gq
        self.assertAlmostEqual(np.abs(y[-500:]).mean(), target, delta=target*0.2)

    # verify-tier: model — the gain integrates only on accepted samples, so the trajectory is
    # handshake-invariant: the same bit-exact sequence must come out under stalls/backpressure.
    def test_bit_exact_under_backpressure(self):
        n = 2000
        target = 8000
        x  = tone(n, 0.02, 1500)
        xi = [int(round(v.real)) for v in x]
        xq = [int(round(v.imag)) for v in x]
        gi, gq = self.run_agc(xi, xq, target, mu=6, throttle=0.3, ready_rate=0.7)
        mi, mq = agc_model(xi, xq, target, gain_frac=8, mu=6)
        np.testing.assert_array_equal(gi, mi[:n])
        np.testing.assert_array_equal(gq, mq[:n])

    def test_delayed_feedback_bit_exact_under_backpressure(self):
        n, target = 2400, 9000
        x  = tone(n, 0.031, 1800)
        xi = [int(round(v.real)) for v in x]
        xq = [int(round(v.imag)) for v in x]
        gi, gq = self.run_agc(xi, xq, target, mu=6, throttle=0.35, ready_rate=0.65,
            delayed_feedback=True)
        mi, mq = agc_model(xi, xq, target, gain_frac=8, mu=6, delayed_feedback=True)
        np.testing.assert_array_equal(gi, mi)
        np.testing.assert_array_equal(gq, mq)
        self.assertEqual(LiteDSPAGC(with_csr=False, delayed_feedback=True).feedback_delay, 1)
        self.assertAlmostEqual(np.abs(gi[-400:] + 1j*gq[-400:]).mean(), target,
            delta=target*0.2)

if __name__ == "__main__":
    unittest.main()
