#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import random
import unittest

import numpy as np

from litedsp.radar.sonar  import LiteDSPTVG
from litedsp.radar.design import tvg_coefficients

from test.common import run_stream, column
from test.models import tvg_model

def frames(i, q, n):
    return [{"i": int(a), "q": int(b), "first": int(k % n == 0), "last": int(k % n == n - 1)} for k, (a, b) in enumerate(zip(i, q))]

class TestTVG(unittest.TestCase):
    # verify-tier: model — two 64-bin pulses of random samples with a 30 dB/decade + absorption
    # + offset law, plain and bypassed, bit-exact under backpressure; pinned latency 6.
    def test_bit_exact(self):
        prng = random.Random(1)
        i = [prng.randint(-2000, 2000) for _ in range(2*64)]
        q = [prng.randint(-2000, 2000) for _ in range(2*64)]
        beats = frames(i, q, 64)
        first = [b["first"] for b in beats]
        g0, k_log, k_lin = tvg_coefficients(30.0, 0.05, -3.0)
        for bypass in (0, 1):
            with self.subTest(bypass=bypass):
                dut = LiteDSPTVG(n_range_bins=64, with_csr=False)
                dut.g0.reset, dut.k_log.reset, dut.k_lin.reset, dut.bypass.reset = g0, k_log, k_lin, bypass
                cap = run_stream(dut, beats, 2*64, ["i", "q", "first", "last"], ["i", "q", "first", "last"],
                    sink_throttle=0.2, source_ready_rate=0.7)
                ri, rq = tvg_model(i, q, first, 64, g0, k_log, k_lin, bypass=bypass)
                self.assertEqual(column(cap, "i", 16).tolist(), ri.tolist())
                self.assertEqual(column(cap, "q", 16).tolist(), rq.tolist())
                self.assertEqual(column(cap, "first").tolist(), first)
                self.assertEqual(dut.latency, 6)

    # verify-tier: bound — a 20 dB/decade law (gain = r) on a constant input over 256 bins:
    # the applied gain follows 20 log10(r) within 0.2 dB from bin 4 to 255; a 60 dB/decade law
    # clamps at 2^max_gain_log2 and a full-scale input sets the sticky saturation flag.
    def test_law_and_saturation(self):
        N = 256
        i = [100]*N; q = [-100]*N
        beats = frames(i, q, N)
        g0, k_log, k_lin = tvg_coefficients(20.0, 0.0, 0.0)
        dut = LiteDSPTVG(n_range_bins=N, with_csr=False)
        dut.g0.reset, dut.k_log.reset, dut.k_lin.reset = g0, k_log, k_lin
        cap = run_stream(dut, beats, N, ["i", "q", "first", "last"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16).astype(float)
        for r in range(4, N):
            self.assertLessEqual(abs(20*math.log10(y[r]/100.0) - 20*math.log10(r)), 0.2, r)
        g0, k_log, k_lin = tvg_coefficients(60.0, 0.0, 0.0)
        dut = LiteDSPTVG(n_range_bins=N, with_csr=False)
        dut.g0.reset, dut.k_log.reset, dut.k_lin.reset = g0, k_log, k_lin
        cap = run_stream(dut, frames([30000]*N, [0]*N, N), N, ["i", "q", "first", "last"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0, extra=[self._read_sat(dut)])
        self.assertEqual(self.sat, 1)
        self.assertEqual(int(column(cap, "i", 16).max()), 32767)
        for kwargs in ({"n_range_bins": 1}, {"gain_frac": 0}, {"max_gain_log2": 13}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPTVG(with_csr=False, **kwargs)

    def _read_sat(self, dut):
        from migen import passive
        @passive
        def gen():
            while True:
                self.sat = (yield dut.saturated)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
