#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.farrow import LiteDSPFarrowInterpolator

from test.common import run_stream, column, snr_db, assert_snr

class TestFarrow(unittest.TestCase):
    # verify-tier: bound — cubic interpolation of an oversampled tone at mu=0.5 vs the ideal
    # fractionally-delayed cosine (integer alignment searched, amplitude/phase fixed by the
    # stimulus). Measured 87.5 dB (LITEDSP_SEED=0); gate 3 dB under.
    def test_fractional_delay(self):
        n  = 2000
        f  = 0.02
        mu = 0.5
        x  = np.round(15000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        dut = LiteDSPFarrowInterpolator(data_width=16, frac_bits=15, with_csr=False)
        dut.mu.reset = int(round(mu*(1 << 15)))
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n - 4,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16).astype(float)[16:]
        # Compare to the ideal cosine sampled at a fractional offset (search integer alignment).
        best_snr, best_ref = -np.inf, None
        for d in range(0, 25):
            ref = 15000*np.cos(2*np.pi*f*(np.arange(len(y)) + d + mu))
            s   = snr_db(ref, y)
            if s > best_snr:
                best_snr, best_ref = s, ref
        assert_snr(self, best_ref, y, 84.0, "farrow fractional delay")

if __name__ == "__main__":
    unittest.main()
