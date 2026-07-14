#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.comm.pll import LiteDSPPLL, LiteDSPCostas

from test.common import run_stream, column

class TestPLL(unittest.TestCase):
    def test_locks_to_tone(self):
        n = 8000
        f = 0.01
        x = 12000*np.exp(1j*2*np.pi*f*np.arange(n))
        dut = LiteDSPPLL(data_width=16, kp_shift=4, ki_shift=12, with_csr=False)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        y = y[3*n//4:]                                   # After lock.
        # Derotated tone should sit at a near-constant phase (low AC vs DC).
        self.assertGreater(np.abs(y.mean()), 8000)
        self.assertLess(y.std(), np.abs(y.mean())/4)

class TestCostas(unittest.TestCase):
    def test_recovers_bpsk(self):
        n = 12000
        f = 0.005
        rng = np.random.RandomState(0)
        bits = rng.randint(0, 2, n)
        data = 2*bits - 1                                 # +/-1 BPSK.
        x = 11000*data*np.exp(1j*2*np.pi*f*np.arange(n))
        dut = LiteDSPCostas(data_width=16, kp_shift=4, ki_shift=12, with_csr=False)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        di = column(cap, "i", 16).astype(float)[3*n//4:]
        dq = column(cap, "q", 16).astype(float)[3*n//4:]
        # After lock: data on I (large |I|), quadrature noise small.
        self.assertGreater(np.abs(di).mean(), 6000)
        self.assertLess(np.abs(dq).mean(), np.abs(di).mean()/4)
        # Recovered bits (sign of I) match data up to a global sign ambiguity.
        rec = (di >= 0).astype(int)
        ref = bits[3*n//4:3*n//4 + len(rec)]
        agree = np.mean(rec == ref)
        self.assertTrue(agree > 0.97 or agree < 0.03)    # BPSK sign ambiguity.

if __name__ == "__main__":
    unittest.main()
