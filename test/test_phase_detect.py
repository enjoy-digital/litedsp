#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.comm.phase_detect import LiteDSPPhaseDetect

from test.common import run_stream, column, to_signed

class TestPhaseDetect(unittest.TestCase):
    def test_angle(self):
        dut = LiteDSPPhaseDetect(data_width=16, angle_width=16, with_csr=False)
        angs = np.linspace(-np.pi*0.9, np.pi*0.9, 64)
        pts  = [(int(12000*np.cos(a)), int(12000*np.sin(a))) for a in angs]
        cap  = run_stream(dut, [{"i": i, "q": q} for i, q in pts], len(pts), ["i", "q"], ["angle"],
            sink_throttle=0.0, source_ready_rate=1.0)
        got = to_signed(column(cap, "angle"), 16)/(1 << 16)*2*np.pi
        err = np.angle(np.exp(1j*(got - angs)))
        self.assertLess(np.abs(err).max(), 0.01)

if __name__ == "__main__":
    unittest.main()
