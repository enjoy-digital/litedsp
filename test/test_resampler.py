#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.resampler import LiteDSPRationalResampler

from test.common import run_stream, column, snr_db

class TestRationalResampler(unittest.TestCase):
    def test_ratio(self):
        L, M, n = 3, 2, 600
        f = 0.05
        x = np.round(12000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        dut = LiteDSPRationalResampler(interpolation=L, decimation=M, data_width=16, with_csr=False)
        n_out = n*L//M - 40
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n_out,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16).astype(float)[40:]
        # Output tone at f*M/L; should be a clean sinusoid (compare to ideal, search phase).
        fout = f*M/L
        best = -np.inf
        for ph in np.linspace(0, 2*np.pi, 16, endpoint=False):
            ref = np.std(y)*np.sqrt(2)*np.cos(2*np.pi*fout*np.arange(len(y)) + ph)
            best = max(best, snr_db(ref, y))
        self.assertGreater(best, 15.0)   # Resampled tone preserved (crude amplitude-fit metric).

if __name__ == "__main__":
    unittest.main()
