#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.level.squelch import LiteDSPSquelch

from test.common import run_stream, column

class TestSquelch(unittest.TestCase):
    def test_gates(self):
        dut = LiteDSPSquelch(data_width=16, with_csr=False)
        dut.open_threshold.reset  = 5000**2
        dut.close_threshold.reset = 3000**2
        loud  = [{"i": 8000, "q": 0} for _ in range(20)]
        quiet = [{"i": 100,  "q": 0} for _ in range(20)]
        cap = run_stream(dut, loud + quiet, 40, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        gi = column(cap, "i", 16)
        self.assertGreater(np.abs(gi[5:18]).mean(), 5000)   # loud passes.
        self.assertEqual(np.abs(gi[25:]).sum(), 0)          # quiet muted.

if __name__ == "__main__":
    unittest.main()
