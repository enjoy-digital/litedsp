#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPSlicer tests, bit-exact against ``slicer_model`` (points, symbols, boundaries).

verify-tier: model
"""

import random
import unittest

import numpy as np

from litedsp.comm.slicer import LiteDSPSlicer

from test.common import run_stream, column
from test.models import slicer_model

class TestSlicer(unittest.TestCase):
    def run_slicer(self, xi, xq, bits_per_axis, spacing):
        dut = LiteDSPSlicer(data_width=16, bits_per_axis=bits_per_axis, spacing=spacing,
            with_csr=False)
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
            len(xi), ["i", "q"], ["i", "q", "symbol"])  # Default randomized backpressure.
        return column(cap, "i", 16), column(cap, "q", 16), column(cap, "symbol")

    def test_bit_exact(self):
        for bits_per_axis, spacing in [(1, 8000), (2, 6000)]:
            L    = 1 << bits_per_axis
            prng = random.Random(L)
            # Every decision boundary (at (2j - L + 2)*spacing), hit exactly and one LSB on
            # each side (>= at the boundary decides the upper level), plus extremes and random.
            edges = []
            for j in range(L - 1):
                b = (2*j - L + 2)*spacing
                edges += [b - 1, b, b + 1]
            xi = edges + [-32768, 32767, 0]
            xq = list(reversed(edges)) + [32767, -32768, 0]
            xi += [prng.randint(-32768, 32767) for _ in range(200)]
            xq += [prng.randint(-32768, 32767) for _ in range(200)]
            gi, gq, gs = self.run_slicer(xi, xq, bits_per_axis, spacing)
            ri, rq, rs = slicer_model(xi, xq, bits_per_axis=bits_per_axis, spacing=spacing)
            self.assertTrue(np.array_equal(gi, ri), f"I mismatch L={L}")
            self.assertTrue(np.array_equal(gq, rq), f"Q mismatch L={L}")
            self.assertTrue(np.array_equal(gs, rs), f"symbol mismatch L={L}")

    def test_qpsk_known_mapping(self):
        # Functional intent: QPSK quadrant decisions ([q_bit | i_bit] symbol packing).
        pts = [(5000, -7000), (-3000, 2000), (9000, 9000), (-1000, -1000)]
        gi, gq, gs = self.run_slicer([p[0] for p in pts], [p[1] for p in pts], 1, 8000)
        self.assertTrue(np.array_equal(gi, [ 8000, -8000, 8000, -8000]))
        self.assertTrue(np.array_equal(gq, [-8000,  8000, 8000, -8000]))
        self.assertTrue(np.array_equal(gs, [0b01, 0b10, 0b11, 0b00]))

if __name__ == "__main__":
    unittest.main()
