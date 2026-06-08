#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.arb_resampler import ArbResampler
from litedsp.analysis.welch       import WelchPSD

from test.common import run_stream, column, snr_db

class TestArbResampler(unittest.TestCase):
    def test_noninteger_ratio(self):
        ratio = 1.5                                   # Decimate by 1.5.
        n, f  = 900, 0.04
        x = np.round(12000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        dut = ArbResampler(data_width=16, frac=15, with_csr=False)
        dut.ratio.reset = int(round(ratio*(1 << 15)))
        n_out = int(n/ratio) - 20
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n_out,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16).astype(float)[20:]
        fout = f*ratio
        best = -np.inf
        for ph in np.linspace(0, 2*np.pi, 24, endpoint=False):
            ref = np.std(y)*np.sqrt(2)*np.cos(2*np.pi*fout*np.arange(len(y)) + ph)
            best = max(best, snr_db(ref, y))
        self.assertGreater(best, 20.0)

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
        dut = WelchPSD(N=N, data_width=16, avg_log2=avg, window="hann", with_csr=False)
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))], N,
            ["i", "q"], ["data"], sink_throttle=0.0, source_ready_rate=1.0)
        spec = column(cap, "data")
        self.assertEqual(int(np.argmax(spec)), k0)

if __name__ == "__main__":
    unittest.main()
