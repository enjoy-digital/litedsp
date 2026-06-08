#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.filter.cic import CICDecimator, CICInterpolator

from test.common import run_stream, column
from test.models import cic_decimator_model, cic_interpolator_model

class TestCICDecimator(unittest.TestCase):
    def run_dec(self, xi, xq, R, N, M=1):
        dut = CICDecimator(data_width=16, R=R, N=N, M=M, with_csr=False)
        n_out = len(xi)//R
        samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
        cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.6)
        return column(cap, "i", 16), column(cap, "q", 16), n_out

    def test_bit_exact(self):
        for R, N in [(4, 3), (8, 4), (5, 2)]:
            prng = random.Random(R*N)
            xi = [prng.randint(-2000, 2000) for _ in range(R*40)]
            xq = [prng.randint(-2000, 2000) for _ in range(R*40)]
            gi, gq, n_out = self.run_dec(xi, xq, R, N)
            ri = cic_decimator_model(xi, R, N)[:n_out]
            rq = cic_decimator_model(xq, R, N)[:n_out]
            self.assertTrue(np.array_equal(gi, ri), f"I R={R} N={N}")
            self.assertTrue(np.array_equal(gq, rq), f"Q R={R} N={N}")

    def test_alias_rejection(self):
        # Tone above the output Nyquist must be strongly attenuated vs an in-band tone.
        R, N, n = 8, 4, 8*400
        t = np.arange(n)
        lo = np.round(1500*np.cos(2*np.pi*0.01*t)).astype(int)     # in band.
        hi = np.round(1500*np.cos(2*np.pi*0.20*t)).astype(int)     # above out-Nyquist (0.0625).
        gi_lo, _, _ = self.run_dec(list(lo), [0]*n, R, N)
        gi_hi, _, _ = self.run_dec(list(hi), [0]*n, R, N)
        self.assertGreater(gi_lo[len(gi_lo)//2:].std(), 10*gi_hi[len(gi_hi)//2:].std())

class TestCICInterpolator(unittest.TestCase):
    def run_int(self, xi, xq, R, N, M=1):
        dut = CICInterpolator(data_width=16, R=R, N=N, M=M, with_csr=False)
        n_out = len(xi)*R
        samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
        cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.6)
        return column(cap, "i", 16), column(cap, "q", 16), n_out

    def test_bit_exact(self):
        for R, N in [(4, 3), (8, 2)]:
            prng = random.Random(R*N + 1)
            xi = [prng.randint(-3000, 3000) for _ in range(60)]
            xq = [prng.randint(-3000, 3000) for _ in range(60)]
            gi, gq, n_out = self.run_int(xi, xq, R, N)
            ri = cic_interpolator_model(xi, R, N)[:n_out]
            rq = cic_interpolator_model(xq, R, N)[:n_out]
            self.assertTrue(np.array_equal(gi, ri), f"I R={R} N={N}")
            self.assertTrue(np.array_equal(gq, rq), f"Q R={R} N={N}")

if __name__ == "__main__":
    unittest.main()
