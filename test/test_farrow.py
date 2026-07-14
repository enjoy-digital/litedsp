#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.farrow import LiteDSPFarrowInterpolator

from test.common import run_stream, column, snr_db

class TestFarrow(unittest.TestCase):
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
        best = -np.inf
        for d in range(0, 25):
            ref = 15000*np.cos(2*np.pi*f*(np.arange(len(y)) + d + mu))
            best = max(best, snr_db(ref, y))
        self.assertGreater(best, 35.0)

if __name__ == "__main__":
    unittest.main()
