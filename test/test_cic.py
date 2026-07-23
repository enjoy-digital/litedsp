#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import passive

from litedsp.filter.cic import LiteDSPCICDecimator, LiteDSPCICInterpolator, LiteDSPCICDecimatorRuntime, cic_shift

from test.common import run_stream, column
from test.models import cic_decimator_model, cic_interpolator_model

class TestCICDecimator(unittest.TestCase):
    def run_dec(self, xi, xq, R, N, M=1, staged=False):
        dut = LiteDSPCICDecimator(data_width=16, decimation=R, n_stages=N, diff_delay=M,
            with_csr=False, staged=staged)
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

    def test_staged_bit_exact(self):
        for R, N, M in [(4, 3, 1), (8, 4, 1), (5, 2, 2)]:
            prng = random.Random(100*R + 10*N + M)
            xi = [prng.randint(-2000, 2000) for _ in range(R*32)]
            xq = [prng.randint(-2000, 2000) for _ in range(R*32)]
            gi, gq, n_out = self.run_dec(xi, xq, R, N, M, staged=True)
            self.assertTrue(np.array_equal(gi, cic_decimator_model(xi, R, N, M)[:n_out]))
            self.assertTrue(np.array_equal(gq, cic_decimator_model(xq, R, N, M)[:n_out]))
            self.assertEqual(LiteDSPCICDecimator(decimation=R, n_stages=N,
                with_csr=False, staged=True).latency, 2*N)

    def test_alias_rejection(self):
        # Tone above the output Nyquist must be strongly attenuated vs an in-band tone.
        R, N, n = 8, 4, 8*400
        t = np.arange(n)
        lo = np.round(1500*np.cos(2*np.pi*0.01*t)).astype(int)     # in band.
        hi = np.round(1500*np.cos(2*np.pi*0.20*t)).astype(int)     # above out-Nyquist (0.0625).
        gi_lo, _, _ = self.run_dec(list(lo), [0]*n, R, N)
        gi_hi, _, _ = self.run_dec(list(hi), [0]*n, R, N)
        self.assertGreater(gi_lo[len(gi_lo)//2:].std(), 10*gi_hi[len(gi_hi)//2:].std())

class TestCICDecimatorRuntime(unittest.TestCase):
    def run_dec(self, xi, xq, R, N, staged=False):
        dut = LiteDSPCICDecimatorRuntime(data_width=16, r_max=8192, n_stages=N, iq=True,
            with_csr=False, staged=staged)
        n_out = len(xi)//R

        @passive
        def cfg():
            yield dut.rate.eq(R)
            yield dut.shift.eq(cic_shift(R, N))
            while True:
                yield

        samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
        cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.6, extra=[cfg()])
        return column(cap, "i", 16), column(cap, "q", 16), n_out

    def test_bit_exact_matches_fixed_cic_at_runtime_rates(self):
        # The runtime CIC must match the build-time CIC golden model for each configured rate.
        for R, N in [(4, 3), (8, 4), (16, 4), (32, 3)]:
            prng = random.Random(R*N + 7)
            xi = [prng.randint(-2000, 2000) for _ in range(R*40)]
            xq = [prng.randint(-2000, 2000) for _ in range(R*40)]
            gi, gq, n_out = self.run_dec(xi, xq, R, N)
            ri = cic_decimator_model(xi, R, N)[:n_out]
            rq = cic_decimator_model(xq, R, N)[:n_out]
            self.assertTrue(np.array_equal(gi, ri), f"I R={R} N={N}")
            self.assertTrue(np.array_equal(gq, rq), f"Q R={R} N={N}")

    def test_staged_bit_exact_at_runtime_rates(self):
        # The staged (timing-friendly) architecture must match the same golden model, modulo
        # its documented n_stages-input-sample group delay. It requires R >= 2*n_stages + 4
        # (an output must drain before the next window closes).
        for R, N in [(12, 4), (16, 4), (32, 3), (64, 4)]:
            prng = random.Random(R*N + 11)
            xi = [prng.randint(-2000, 2000) for _ in range(R*40)]
            xq = [prng.randint(-2000, 2000) for _ in range(R*40)]
            gi, gq, n_out = self.run_dec(xi, xq, R, N, staged=True)
            ri = cic_decimator_model([0]*N + xi, R, N)[:n_out]
            rq = cic_decimator_model([0]*N + xq, R, N)[:n_out]
            self.assertTrue(np.array_equal(gi, ri), f"I R={R} N={N} staged")
            self.assertTrue(np.array_equal(gq, rq), f"Q R={R} N={N} staged")

class TestCICInterpolator(unittest.TestCase):
    def run_int(self, xi, xq, R, N, M=1, staged=False):
        dut = LiteDSPCICInterpolator(data_width=16, interpolation=R, n_stages=N, diff_delay=M,
            with_csr=False, staged=staged)
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

    def test_staged_bit_exact(self):
        for R, N, M in [(4, 3, 1), (8, 2, 1), (5, 2, 2)]:
            prng = random.Random(200*R + 10*N + M)
            xi = [prng.randint(-3000, 3000) for _ in range(32)]
            xq = [prng.randint(-3000, 3000) for _ in range(32)]
            gi, gq, n_out = self.run_int(xi, xq, R, N, M, staged=True)
            self.assertTrue(np.array_equal(gi, cic_interpolator_model(xi, R, N, M)[:n_out]))
            self.assertTrue(np.array_equal(gq, cic_interpolator_model(xq, R, N, M)[:n_out]))
            self.assertEqual(LiteDSPCICInterpolator(interpolation=R, n_stages=N,
                with_csr=False, staged=True).latency, 2*N)

if __name__ == "__main__":
    unittest.main()
