#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.correction.dc_offset import DCOffset
from litedsp.correction.cfo       import Derotator

from test.common import run_stream, column
from test.models import dc_offset_model

def tone(n, f, amp):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

class TestDCOffset(unittest.TestCase):
    def test_bit_exact(self):
        dut  = DCOffset(data_width=16, mu=8, with_csr=False)
        prng = random.Random(1)
        xi = [prng.randint(-20000, 20000) for _ in range(400)]
        xq = [prng.randint(-20000, 20000) for _ in range(400)]
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
            len(xi), ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "i", 16), dc_offset_model(xi, 8)))
        self.assertTrue(np.array_equal(column(cap, "q", 16), dc_offset_model(xq, 8)))

    def test_removes_dc(self):
        n = 4000
        x = (6000 + 5000*np.cos(2*np.pi*0.03*np.arange(n))).astype(int)
        dut = DCOffset(data_width=16, mu=7, with_csr=False)
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        out = column(cap, "i", 16)[n//2:]
        self.assertLess(abs(out.mean()), 60)
        self.assertGreater(out.std(), 2000)

class TestDerotator(unittest.TestCase):
    def test_shift_to_dc(self):
        n = 1024
        f = 0.12
        dut = Derotator(data_width=16, with_csr=False)
        dut.nco.phase_inc.reset = int(round(f*(1 << 32))) & 0xffffffff
        x = tone(n, f, 12000)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n - 4, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = (column(cap, "i", 16) + 1j*column(cap, "q", 16))[n//2:]
        self.assertGreater(np.abs(y.mean()), 8000)          # tone moved to DC.
        self.assertLess(y.std(), np.abs(y.mean())/8 + 1)

if __name__ == "__main__":
    unittest.main()
