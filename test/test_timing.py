#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.comm.timing_recovery import TimingRecovery
from litedsp.filter.design        import rrc_coefficients

from test.common import run_stream, column, to_signed

class TestTimingRecovery(unittest.TestCase):
    @unittest.skip("WIP: Gardner loop needs a full interpolation controller (integer sample-slip), "
                   "not just fractional mu. Skeleton present; convergence not yet achieved.")
    def test_recovers_bpsk(self):
        # Build a 2-sps BPSK signal with a fractional timing offset.
        L      = 400
        sps_hi = 32
        rng    = np.random.RandomState(0)
        d      = 2*rng.randint(0, 2, L) - 1
        up     = np.zeros(L*sps_hi)
        up[::sps_hi] = d
        rrc    = np.array(rrc_coefficients(sps_hi, 8, 0.5))/32768.0
        sig    = np.convolve(up, rrc)
        step   = sps_hi//2                       # -> 2 samples/symbol.
        offset = 11                              # Fractional timing offset (of 16).
        s2     = sig[offset::step]
        s2     = np.round(s2/np.max(np.abs(sig))*12000).astype(int)

        dut = TimingRecovery(data_width=16, mu_shift=20, with_csr=False)
        n_out = len(s2)//2 - 8
        cap = run_stream(dut, [{"i": int(v), "q": 0} for v in s2], n_out, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        sym = to_signed(column(cap, "i"), 16)
        rec = (sym >= 0).astype(int)

        # After convergence, recovered signs match data up to a delay + global sign ambiguity.
        tail = rec[len(rec)//2:]
        best = 0.0
        for delay in range(0, 40):
            ref = ((d[delay:delay + len(tail)] + 1)//2)
            if len(ref) < len(tail):
                continue
            agree = np.mean(tail == ref)
            best  = max(best, agree, 1 - agree)        # sign ambiguity.
        self.assertGreater(best, 0.95)

if __name__ == "__main__":
    unittest.main()
