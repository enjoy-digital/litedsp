#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.extra import LiteDSPNotch, LiteDSPCombFilter, LiteDSPAllpass

from test.common import run_stream, column

def tone(n, f, amp=12000):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

def run_iq(dut, x, skip=64):
    n = len(x)
    cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
        n - 4, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
    return (column(cap, "i", 16) + 1j*column(cap, "q", 16))[skip:]

class TestNotch(unittest.TestCase):
    def test_attenuates_notch_freq(self):
        f0 = 0.12
        dut = LiteDSPNotch(data_width=16, r=0.97, with_csr=False)
        dut.cos_w0.reset = int(round(np.cos(2*np.pi*f0)*(1 << 14)))
        at  = run_iq(dut, tone(3000, f0))            # at the notch.
        dut2 = LiteDSPNotch(data_width=16, r=0.97, with_csr=False)
        dut2.cos_w0.reset = int(round(np.cos(2*np.pi*f0)*(1 << 14)))
        off = run_iq(dut2, tone(3000, f0 + 0.25))    # well away.
        self.assertGreater(np.abs(off).mean(), 8*np.abs(at).mean())

class TestComb(unittest.TestCase):
    def test_nulls(self):
        D = 8
        dut = LiteDSPCombFilter(depth=D, data_width=16, with_csr=False)
        at  = run_iq(dut, tone(2000, 1.0/D))         # null at f = 1/D.
        dut2 = LiteDSPCombFilter(depth=D, data_width=16, with_csr=False)
        off = run_iq(dut2, tone(2000, 0.5/D))        # between nulls.
        self.assertGreater(np.abs(off).mean(), 8*np.abs(at).mean())

class TestAllpass(unittest.TestCase):
    def test_flat_magnitude(self):
        dut = LiteDSPAllpass(data_width=16, with_csr=False)
        dut.a.reset = int(round(0.6*(1 << 14)))
        for f in [0.05, 0.2, 0.4]:
            d = LiteDSPAllpass(data_width=16, with_csr=False)
            d.a.reset = int(round(0.6*(1 << 14)))
            y = run_iq(d, tone(3000, f, amp=12000))
            self.assertAlmostEqual(np.abs(y).mean(), 12000, delta=12000*0.05)

if __name__ == "__main__":
    unittest.main()
