#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.halfband import LiteDSPHalfbandDecimator

from test.common import run_stream, column

def tone(n, f, amp=12000):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

class TestHalfband(unittest.TestCase):
    def test_decimate_anti_alias(self):
        n = 2*300
        def run(x):
            dut = LiteDSPHalfbandDecimator(n_taps=23, data_width=16, with_csr=False)
            samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
            cap = run_stream(dut, samples, n//2 - 16, ["i", "q"], ["i", "q"],
                sink_throttle=0.0, source_ready_rate=1.0)
            return column(cap, "i", 16) + 1j*column(cap, "q", 16)
        inb = run(tone(n, 0.05))
        oob = run(tone(n, 0.45))   # near input Nyquist -> should be killed by halfband.
        self.assertGreater(np.abs(inb[len(inb)//2:]).mean(), 8*np.abs(oob[len(oob)//2:]).mean())

if __name__ == "__main__":
    unittest.main()
