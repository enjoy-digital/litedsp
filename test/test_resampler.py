#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.resampler import LiteDSPRationalResampler

from test.common import run_stream, column, assert_snr

class TestRationalResampler(unittest.TestCase):
    # verify-tier: bound — the output must be a clean tone at f*M/L: least-squares-fit the
    # expected sinusoid (amplitude/phase are the only free parameters), so the residual is the
    # resampler's passband distortion. Measured 87.5 dB (LITEDSP_SEED=0); gate 3 dB under.
    def test_ratio(self):
        L, M, n = 3, 2, 600
        f = 0.05
        x = np.round(12000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        dut = LiteDSPRationalResampler(interpolation=L, decimation=M, data_width=16, with_csr=False)
        n_out = n*L//M - 40
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n_out,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16).astype(float)[40:]
        # Output tone at f*M/L; should be a clean sinusoid (compare to the LS-fitted ideal).
        fout  = f*M/L
        t     = np.arange(len(y))
        basis = np.column_stack([np.cos(2*np.pi*fout*t), np.sin(2*np.pi*fout*t)])
        ref   = basis @ np.linalg.lstsq(basis, y, rcond=None)[0]
        assert_snr(self, ref, y, 84.0, "rational resampler tone")

if __name__ == "__main__":
    unittest.main()
