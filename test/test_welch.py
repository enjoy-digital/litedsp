#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.analysis.welch import LiteDSPWelchPSD

from test.common import run_stream, column
from test.models import welch_model

class TestWelchPSD(unittest.TestCase):
    def test_tone_spectrum(self):
        N, avg = 128, 2
        k0 = 19
        t = np.arange(N)
        fi = np.round(9000*np.cos(2*np.pi*k0*t/N)).astype(int)
        fq = np.round(9000*np.sin(2*np.pi*k0*t/N)).astype(int)
        nfr = (1 << avg) + 3
        xi = list(fi)*nfr + list(fi)
        xq = list(fq)*nfr + list(fq)
        dut = LiteDSPWelchPSD(N=N, data_width=16, avg_log2=avg, window="hann", with_csr=False)
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))], N,
            ["i", "q"], ["data"], sink_throttle=0.0, source_ready_rate=1.0)
        spec = column(cap, "data")
        self.assertEqual(int(np.argmax(spec)), k0)

    def test_tone_spectrum_overlap(self):
        # Same tone detection with 50% segment overlap (input replayed from the history RAM).
        N, avg = 128, 2
        k0 = 19
        t = np.arange(N)
        fi = np.round(9000*np.cos(2*np.pi*k0*t/N)).astype(int)
        fq = np.round(9000*np.sin(2*np.pi*k0*t/N)).astype(int)
        nfr = (1 << avg) + 3
        xi = list(fi)*nfr + list(fi)
        xq = list(fq)*nfr + list(fq)
        dut = LiteDSPWelchPSD(N=N, data_width=16, avg_log2=avg, window="hann", overlap=50,
            with_csr=False)
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))], N,
            ["i", "q"], ["data"], sink_throttle=0.0, source_ready_rate=1.0)
        spec = column(cap, "data")
        self.assertEqual(int(np.argmax(spec)), k0)

    def test_bit_exact_vs_model(self):
        # Small config against the golden model (window + fixed-point FFT + PSD, overlapped).
        N, avg = 16, 1
        rng = np.random.default_rng(3)
        xi  = rng.integers(-20000, 20000, 80)
        xq  = rng.integers(-20000, 20000, 80)
        for overlap in (0, 25, 50, 75):
            dut = LiteDSPWelchPSD(N=N, data_width=16, avg_log2=avg, window="hann",
                overlap=overlap, with_csr=False)
            cap = run_stream(dut, [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))],
                2*N, ["i", "q"], ["data"], sink_throttle=0.2, source_ready_rate=0.8)
            got = column(cap, "data")
            ref = np.concatenate(welch_model(xi, xq, N, avg_log2=avg, window="hann",
                overlap=overlap)[:2])
            self.assertEqual(got.tolist(), ref.tolist(), f"overlap {overlap}% mismatch vs welch_model")

    def test_overlap_variance_reduction(self):
        # For the same input length, 50% overlap doubles the segment count (avg_log2 + 1) and
        # lowers the variance of the noise-floor estimate vs the non-overlapped chain.
        N = 64
        n_spectra = 3
        rng = np.random.default_rng(1234)
        n  = 8*(1 << 3)*N  # Plenty of input for both configurations (driver is passive).
        xi = rng.integers(-8000, 8000, n)
        xq = rng.integers(-8000, 8000, n)
        samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(n)]
        rel_var = {}
        # Both configurations consume ~4*N input samples per emitted spectrum.
        for overlap, avg in [(0, 2), (50, 3)]:
            dut = LiteDSPWelchPSD(N=N, data_width=16, avg_log2=avg, window="hann",
                overlap=overlap, with_csr=False)
            cap  = run_stream(dut, samples, n_spectra*N, ["i", "q"], ["data"],
                sink_throttle=0.0, source_ready_rate=1.0)
            spec = column(cap, "data").astype(float)
            rel_var[overlap] = np.var(spec)/np.mean(spec)**2
        self.assertLess(rel_var[50], rel_var[0])

    def test_overlap_validation(self):
        with self.assertRaises(ValueError):
            LiteDSPWelchPSD(N=64, overlap=30)   # Not one of 0/25/50/75.
        with self.assertRaises(ValueError):
            LiteDSPWelchPSD(N=2,  overlap=25)   # N*overlap/100 not an integer.

if __name__ == "__main__":
    unittest.main()
