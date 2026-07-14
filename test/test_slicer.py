#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.comm.slicer import LiteDSPSlicer

from test.common import run_stream, column

class TestSlicer(unittest.TestCase):
    def test_qpsk(self):
        dut = LiteDSPSlicer(data_width=16, bits_per_axis=1, spacing=8000, with_csr=False)
        pts = [(5000, -7000), (-3000, 2000), (9000, 9000), (-1000, -1000)]
        cap = run_stream(dut, [{"i": i, "q": q} for i, q in pts], len(pts), ["i", "q"],
            ["i", "q", "symbol"], sink_throttle=0.0, source_ready_rate=1.0)
        gi = column(cap, "i", 16)
        gq = column(cap, "q", 16)
        self.assertTrue(np.array_equal(np.sign(gi), [1, -1, 1, -1]))
        self.assertTrue(np.array_equal(np.sign(gq), [-1, 1, 1, -1]))

if __name__ == "__main__":
    unittest.main()
