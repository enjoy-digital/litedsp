#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.comm.correlator import LiteDSPCorrelator

from test.common import run_stream, column

class TestCorrelator(unittest.TestCase):
    def test_peak_on_alignment(self):
        code = [1, 1, 1, -1, -1, 1, -1]      # Barker-7.
        dut  = LiteDSPCorrelator(code, data_width=16, with_csr=False)
        amp  = 4000
        # Stream: noise-ish zeros, then the code, then zeros.
        seq  = [0]*10 + [c*amp for c in code] + [0]*10
        cap  = run_stream(dut, [{"i": v, "q": 0} for v in seq], len(seq), ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        gi = np.abs(column(cap, "i", 16))
        peak = gi.max()
        # Peak (full correlation = 7*amp scaled) clearly above off-peak.
        self.assertGreater(peak, 5*np.median(gi[gi > 0]) if (gi > 0).any() else 0)

if __name__ == "__main__":
    unittest.main()
