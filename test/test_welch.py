#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.analysis.welch import LiteDSPWelchPSD

from test.common import run_stream, column

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

if __name__ == "__main__":
    unittest.main()
