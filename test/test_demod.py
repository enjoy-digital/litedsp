#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.comm.fm_demod import LiteDSPFMDemod
from litedsp.comm.am_demod import LiteDSPAMDemod

from test.common import run_stream, column, to_signed

def corr(a, b):
    a = a - a.mean()
    b = b - b.mean()
    return float(np.sum(a*b)/np.sqrt(np.sum(a*a)*np.sum(b*b)))

class TestFMDemod(unittest.TestCase):
    def test_recovers_message(self):
        n  = 4000
        fm = 0.003
        msg = np.cos(2*np.pi*fm*np.arange(n))
        f_dev = 0.05
        phase = 2*np.pi*np.cumsum(f_dev*msg)
        x = 14000*np.exp(1j*phase)
        dut = LiteDSPFMDemod(data_width=16, angle_width=16, with_csr=False)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n - 4, ["i", "q"], ["data"], sink_throttle=0.0, source_ready_rate=1.0)
        y = to_signed(column(cap, "data"), 16).astype(float)[64:]
        self.assertGreater(corr(y, msg[64:64 + len(y)]), 0.99)

class TestAMDemod(unittest.TestCase):
    def test_recovers_message(self):
        n  = 4000
        fm = 0.004
        fc = 0.05
        msg = np.cos(2*np.pi*fm*np.arange(n))
        env = 12000 + 6000*msg
        x   = env*np.exp(1j*2*np.pi*fc*np.arange(n))
        dut = LiteDSPAMDemod(data_width=16, pole_shift=9, with_csr=False)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n - 4, ["i", "q"], ["data"], sink_throttle=0.0, source_ready_rate=1.0)
        w = dut.source.data.nbits
        y = to_signed(column(cap, "data"), w).astype(float)[n//4:]
        self.assertGreater(corr(y, msg[n//4:n//4 + len(y)]), 0.95)

if __name__ == "__main__":
    unittest.main()
