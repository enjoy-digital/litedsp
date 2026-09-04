#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.motor.svpwm import LiteDSPSVPWM

from test.common import run_stream, column
from test.models import svpwm_model, inverse_clarke_model

FS = (1 << 15) - 1

def rotating(n, m, turns=3):
    theta = 2*np.pi*np.arange(n)*turns/n
    return (np.round(m*FS*np.cos(theta)).astype(np.int64),
            np.round(m*FS*np.sin(theta)).astype(np.int64))

class TestSVPWM(unittest.TestCase):
    def run_svpwm(self, alpha, beta, injection="minmax", throttle=0.2, ready_rate=0.7, extra=None):
        dut = LiteDSPSVPWM(data_width=16, injection=injection, with_csr=False)
        cap = run_stream(dut, [{"i": int(a), "q": int(b)} for a, b in zip(alpha, beta)],
            len(alpha), ["i", "q"], ["a", "b", "c"], sink_throttle=throttle,
            source_ready_rate=ready_rate, extra=extra)
        return dut, tuple(column(cap, f, 16) for f in ("a", "b", "c"))

    # verify-tier: model — both injection modes, bit-exact under backpressure; the runtime
    # injection bit is pipelined with the sample it was presented with (toggled mid-stream).
    def test_bit_exact(self):
        n    = 300
        prng = random.Random(1)
        alpha = [prng.randint(-FS, FS) for _ in range(n)]
        beta  = [prng.randint(-FS, FS) for _ in range(n)]
        for injection, inj in (("minmax", 1), ("none", 0)):
            with self.subTest(injection=injection):
                dut, got = self.run_svpwm(alpha, beta, injection)
                ref = svpwm_model(alpha, beta, inj)
                for g, r in zip(got, ref):
                    self.assertTrue(np.array_equal(g, r))
                self.assertEqual(dut.latency, 3)
        dut = LiteDSPSVPWM(data_width=16, with_csr=False)
        n_on = 150

        @passive
        def toggle():
            accepted = 0
            while accepted < n_on:
                yield
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    accepted += 1
            yield dut.injection.eq(0)
            while True:
                yield

        cap = run_stream(dut, [{"i": a, "q": b} for a, b in zip(alpha, beta)], n, ["i", "q"],
            ["a", "b", "c"], sink_throttle=0.2, source_ready_rate=0.7, extra=[toggle()])
        ref = svpwm_model(alpha, beta, np.array([1]*n_on + [0]*(n - n_on)))
        for f, r in zip(("a", "b", "c"), ref):
            self.assertTrue(np.array_equal(column(cap, f, 16), r), f)

    # verify-tier: bound — linear range: with injection a rotating vector of magnitude m stays
    # unclipped up to m = 2/sqrt(3) = 1.1547 (phase peak = m*sqrt(3)/2 <= 1.0); without, phase
    # peaks equal m and clip above 1.0. Checked at m = 1.14 and 1.05 (1 % inside the edges).
    def test_linear_range(self):
        n = 720
        for injection, m, clips in (("minmax", 1.14, False), ("minmax", 1.17, True),
                                    ("none", 0.99, False), ("none", 1.05, True)):
            with self.subTest(injection=injection, m=m):
                alpha, beta = rotating(n, m)
                _, got = self.run_svpwm(alpha, beta, injection, throttle=0.0, ready_rate=1.0)
                clipped = any(np.any(np.abs(g) >= FS) for g in got)
                self.assertEqual(clipped, clips)
                if injection == "minmax" and not clips:
                    # Zero-sequence injection: every phase peak is m*sqrt(3)/2, not m.
                    self.assertLess(max(np.max(np.abs(g)) for g in got), m*np.sqrt(3)/2*FS + 4)

    # verify-tier: bound — the zero sequence is invisible line-to-line: a - b of the modulated
    # duties equals a - b of the plain inverse Clarke within the extra rounding (2 LSB).
    def test_line_voltage_preserved(self):
        n = 720
        alpha, beta = rotating(n, 0.8)
        _, (a, b, c) = self.run_svpwm(alpha, beta, "minmax", throttle=0.0, ready_rate=1.0)
        ra, rb, rc = inverse_clarke_model(alpha, beta)
        self.assertLessEqual(np.max(np.abs((a - b) - (ra - rb))), 2)
        self.assertLessEqual(np.max(np.abs((b - c) - (rb - rc))), 2)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            LiteDSPSVPWM(injection="third_harmonic", with_csr=False)

if __name__ == "__main__":
    unittest.main()
