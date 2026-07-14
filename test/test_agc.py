#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.level.agc import LiteDSPAGC

from test.common import run_stream, column

def tone(n, f, amp):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

class TestAGC(unittest.TestCase):
    def test_converges(self):
        n = 6000
        target = 8000
        dut = LiteDSPAGC(data_width=16, gain_frac=8, mu=6, with_csr=False)
        dut.target.reset = target
        x = tone(n, 0.02, 1500)                              # weak input.
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        self.assertAlmostEqual(np.abs(y[-500:]).mean(), target, delta=target*0.2)

if __name__ == "__main__":
    unittest.main()
