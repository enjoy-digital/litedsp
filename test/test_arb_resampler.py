#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.arb_resampler import LiteDSPArbResampler

from test.common import run_stream, column, assert_snr

class TestArbResampler(unittest.TestCase):
    # verify-tier: bound — the output must be a clean tone at f*ratio: least-squares-fit the
    # expected sinusoid (amplitude/phase are the only free parameters), so the residual is the
    # resampler's interpolation distortion. Measured 84.4 dB (LITEDSP_SEED=0); gate 3 dB under.
    def test_noninteger_ratio(self):
        ratio = 1.5                                   # Decimate by 1.5.
        n, f  = 900, 0.04
        x = np.round(12000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        dut = LiteDSPArbResampler(data_width=16, frac=15, with_csr=False)
        dut.ratio.reset = int(round(ratio*(1 << 15)))
        n_out = int(n/ratio) - 20
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n_out,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16).astype(float)[20:]
        fout  = f*ratio
        t     = np.arange(len(y))
        basis = np.column_stack([np.cos(2*np.pi*fout*t), np.sin(2*np.pi*fout*t)])
        ref   = basis @ np.linalg.lstsq(basis, y, rcond=None)[0]
        assert_snr(self, ref, y, 81.0, "arb_resampler tone")

if __name__ == "__main__":
    unittest.main()
