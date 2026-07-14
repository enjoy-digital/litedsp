#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.analysis.fft_iter import LiteDSPFFTIter

from test.common import run_stream, column, snr_db

class TestFFTIter(unittest.TestCase):
    # Fixed-point bound: each radix-2 pass halves the amplitude (1/N overall) and adds a
    # round-half-up step, so quantization noise accumulates and SNR falls with log2(N). Gates
    # are set 3 dB under the values measured at LITEDSP_SEED=0 (65.8/58.5/52.2 dB).
    SNR_GATES = {16: 62.5, 64: 55.0, 256: 49.0}

    # verify-tier: bound — per-size SNR against numpy's FFT (1/N-scaled).
    def test_matches_numpy(self):
        for N in [16, 64, 256]:
            rng = np.random.RandomState(N)
            x = rng.randint(-8000, 8000, N) + 1j*rng.randint(-8000, 8000, N)
            dut = LiteDSPFFTIter(N=N, data_width=16, with_csr=False)
            samples = [{"i": int(x[k].real), "q": int(x[k].imag)} for k in range(N)]
            cap = run_stream(dut, samples, N, ["i", "q"], ["i", "q"],
                sink_throttle=0.0, source_ready_rate=1.0)
            out = column(cap, "i", 16) + 1j*column(cap, "q", 16)
            ref = np.fft.fft(x)/N
            snr = snr_db(ref, out)
            self.assertGreater(snr, self.SNR_GATES[N], f"N={N} SNR={snr:.1f} dB")

    # verify-tier: bound — a pure tone at bin k0 must peak in bin k0.
    def test_tone_bin(self):
        N, k0 = 64, 9
        t = np.arange(N)
        x = 10000*np.exp(1j*2*np.pi*k0*t/N)
        dut = LiteDSPFFTIter(N=N, data_width=16, with_csr=False)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            N, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        mag = np.abs(column(cap, "i", 16) + 1j*column(cap, "q", 16))
        self.assertEqual(int(np.argmax(mag)), k0)

if __name__ == "__main__":
    unittest.main()
