#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.analysis.fft_iter import FFTIter

from test.common import run_stream, column, snr_db

class TestFFTIter(unittest.TestCase):
    def test_matches_numpy(self):
        for N in [16, 64, 256]:
            rng = np.random.RandomState(N)
            x = rng.randint(-8000, 8000, N) + 1j*rng.randint(-8000, 8000, N)
            dut = FFTIter(N=N, data_width=16, with_csr=False)
            samples = [{"i": int(x[k].real), "q": int(x[k].imag)} for k in range(N)]
            cap = run_stream(dut, samples, N, ["i", "q"], ["i", "q"],
                sink_throttle=0.0, source_ready_rate=1.0)
            out = column(cap, "i", 16) + 1j*column(cap, "q", 16)
            ref = np.fft.fft(x)/N
            self.assertGreater(snr_db(ref, out), 45.0, f"N={N}")

    def test_tone_bin(self):
        N, k0 = 64, 9
        t = np.arange(N)
        x = 10000*np.exp(1j*2*np.pi*k0*t/N)
        dut = FFTIter(N=N, data_width=16, with_csr=False)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            N, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        mag = np.abs(column(cap, "i", 16) + 1j*column(cap, "q", 16))
        self.assertEqual(int(np.argmax(mag)), k0)

if __name__ == "__main__":
    unittest.main()
