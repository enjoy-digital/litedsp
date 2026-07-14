#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPSquelch tests, bit-exact against ``squelch_model`` (hysteresis power gate).

verify-tier: model
"""

import random
import unittest

import numpy as np

from litedsp.level.squelch import LiteDSPSquelch

from test.common import run_stream, column
from test.models import squelch_model

class TestSquelch(unittest.TestCase):
    def run_squelch(self, xi, xq, open_thr, close_thr, **kwargs):
        dut = LiteDSPSquelch(data_width=16, with_csr=False)
        dut.open_threshold.reset  = open_thr
        dut.close_threshold.reset = close_thr
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
            len(xi), ["i", "q"], ["i", "q"], **kwargs)
        return column(cap, "i", 16), column(cap, "q", 16)

    def test_bit_exact(self):
        open_thr, close_thr = 5000**2, 3000**2
        prng = random.Random(7)
        # Threshold boundaries: power == open (>= opens), power == close (< closes, so this
        # exact value holds the gate), one LSB below close, plus bursts and a random walk
        # spanning the hysteresis band.
        xi  = [5000, 3000, 2999, 0, 5000, 0, -5000, 4000, -4000]
        xq  = [0,    0,    0,    0, -1,   0, 0,     3000, -3000]
        xi += [8000]*15 + [100]*15 + [4000]*15 + [0]*5   # Loud / quiet / in-band hold.
        xq += [0]*50
        xi += [prng.randint(-8000, 8000) for _ in range(200)]
        xq += [prng.randint(-8000, 8000) for _ in range(200)]
        gi, gq = self.run_squelch(xi, xq, open_thr, close_thr)  # Default backpressure.
        ri, rq = squelch_model(xi, xq, open_thr, close_thr)
        self.assertTrue(np.array_equal(gi, ri), "I mismatch")
        self.assertTrue(np.array_equal(gq, rq), "Q mismatch")

    def test_gates(self):
        # Functional intent: loud signal passes, quiet signal is muted.
        loud  = [8000]*20
        quiet = [100]*20
        gi, _ = self.run_squelch(loud + quiet, [0]*40, 5000**2, 3000**2,
            sink_throttle=0.0, source_ready_rate=1.0)
        self.assertGreater(np.abs(gi[5:18]).mean(), 5000)   # Loud passes.
        self.assertEqual(np.abs(gi[25:]).sum(), 0)          # Quiet muted.

if __name__ == "__main__":
    unittest.main()
