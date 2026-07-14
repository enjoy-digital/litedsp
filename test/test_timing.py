#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.comm.timing_recovery import LiteDSPTimingRecovery
from litedsp.filter.design        import rrc_coefficients

from test.common import run_stream, column, to_signed

def make_signal(L, sps_hi, sps, offset, seed):
    rng = np.random.RandomState(seed)
    d   = (2*rng.randint(0, 2, L) - 1) + 1j*(2*rng.randint(0, 2, L) - 1)
    up  = np.zeros(L*sps_hi, complex)
    up[::sps_hi] = d
    r   = np.array(rrc_coefficients(sps_hi, 8, 0.35))/32768.0
    sig = np.convolve(np.convolve(up, r), r)             # Raised-cosine (ISI-free at centers).
    sig = sig/np.max(np.abs(sig))
    x   = sig[offset::sps_hi//sps]                        # `sps` samples/symbol with a timing offset.
    return d, np.round(x*11000).astype(complex)

class TestTimingRecovery(unittest.TestCase):
    def run_mm(self, x, sps=2, ted="mm"):
        dut = LiteDSPTimingRecovery(data_width=16, sps=sps, gain_mu=0.1, ted=ted, with_csr=False)
        samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
        n_out = len(x)//sps - 8
        cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        return to_signed(column(cap, "i"), 16) + 1j*to_signed(column(cap, "q"), 16)

    def test_eye_opens(self):
        d, x = make_signal(L=900, sps_hi=32, sps=2, offset=7, seed=0)
        y = self.run_mm(x)
        tail = y[len(y)//2:]
        # Locked timing -> tight QPSK clusters: per-axis |value| has small spread vs its mean.
        for axis in [tail.real, tail.imag]:
            m, s = np.mean(np.abs(axis)), np.std(np.abs(axis))
            self.assertGreater(m, 2000)
            self.assertLess(s/m, 0.25)

    def test_eye_opens_gardner(self):
        d, x = make_signal(L=900, sps_hi=32, sps=2, offset=7, seed=4)
        y = self.run_mm(x, ted="gardner")
        tail = y[len(y)//2:]
        for axis in [tail.real, tail.imag]:
            m, s = np.mean(np.abs(axis)), np.std(np.abs(axis))
            self.assertGreater(m, 2000)
            self.assertLess(s/m, 0.25)

    def test_symbol_error_rate(self):
        d, x = make_signal(L=900, sps_hi=32, sps=2, offset=7, seed=1)
        y = self.run_mm(x)
        seg = y[len(y)//2:len(y)//2 + 200]               # Post-lock segment.
        ri, rq = np.sign(seg.real).astype(int), np.sign(seg.imag).astype(int)
        di, dq = np.sign(d.real).astype(int), np.sign(d.imag).astype(int)
        best = 1.0
        for off in range(0, len(d) - len(seg)):           # Locate the segment within the data.
            for si in (1, -1):
                for sq in (1, -1):
                    ser = 0.5*(np.mean(ri != si*di[off:off+len(seg)]) +
                               np.mean(rq != sq*dq[off:off+len(seg)]))
                    best = min(best, ser)
        self.assertLess(best, 0.02)

if __name__ == "__main__":
    unittest.main()
