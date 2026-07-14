#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.comm.correlator import LiteDSPCorrelator

from test.common import run_stream, column
from test.models import fir_complex_model

class TestCorrelator(unittest.TestCase):
    def run_correlator(self, code, seq):
        dut = LiteDSPCorrelator(code, data_width=16, with_csr=False)
        cap = run_stream(dut, [{"i": v, "q": 0} for v in seq], len(seq), ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        return column(cap, "i", 16), column(cap, "q", 16)

    # verify-tier: bound — peak-to-sidelobe check on the Barker-7 alignment.
    def test_peak_on_alignment(self):
        code = [1, 1, 1, -1, -1, 1, -1]      # Barker-7.
        amp  = 4000
        # Stream: noise-ish zeros, then the code, then zeros.
        seq  = [0]*10 + [c*amp for c in code] + [0]*10
        gi, _ = self.run_correlator(code, seq)
        gi = np.abs(gi)
        peak = gi.max()
        # Peak (full correlation = 7*amp scaled) clearly above off-peak.
        self.assertGreater(peak, 5*np.median(gi[gi > 0]) if (gi > 0).any() else 0)

    # verify-tier: model — the correlator is a complex FIR whose taps are the time-reversed
    # code scaled to full-scale Q1.15, so the whole output is bit-exact against
    # fir_complex_model with the same coefficient quantization (fixed-seed regression).
    def test_matches_matched_filter_model(self):
        code = [1, 1, 1, -1, -1, 1, -1]      # Barker-7.
        rng  = np.random.RandomState(3)
        seq  = list(rng.randint(-8000, 8000, 64))
        seq[20:27] = [c*4000 for c in code]  # Embed the code mid-stream.
        gi, gq = self.run_correlator(code, seq)
        scale  = (1 << 15) - 1
        coeffs = [int(round(c*scale)) for c in reversed(code)]
        ri, rq = fir_complex_model(seq, [0]*len(seq), coeffs)
        np.testing.assert_array_equal(gi, ri[:len(gi)])
        np.testing.assert_array_equal(gq, rq[:len(gq)])

if __name__ == "__main__":
    unittest.main()
