#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

from litedsp.level.rms import LiteDSPRMS

from test.common import run_stream, column

class TestRMS(unittest.TestCase):
    def test_constant(self):
        dut = LiteDSPRMS(data_width=16, window_log2=5, with_csr=False)
        i, q = 3000, 4000   # |x| = 5000 exactly.
        n = (1 << 5)*4
        cap = run_stream(dut, [{"i": i, "q": q} for _ in range(n)], 3, ["i", "q"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        self.assertTrue(all(abs(int(v) - 5000) <= 1 for v in column(cap, "data")))

if __name__ == "__main__":
    unittest.main()
