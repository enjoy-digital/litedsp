#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPClipper tests, bit-exact against ``clipper_model`` (I and Q, threshold sweep).

verify-tier: model
"""

import random
import unittest

import numpy as np

from litedsp.level.clipper import LiteDSPClipper

from test.common import run_stream, column
from test.models import clipper_model

class TestClipper(unittest.TestCase):
    def run_clip(self, xi, xq, thr):
        dut = LiteDSPClipper(data_width=16, with_csr=False)
        dut.threshold.reset = thr
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
            len(xi), ["i", "q"], ["i", "q"])  # Default randomized throttle/backpressure.
        return column(cap, "i", 16), column(cap, "q", 16)

    def test_bit_exact_threshold_sweep(self):
        for thr in [0, 1, 10000, 32767]:
            prng = random.Random(thr)
            # Boundary vectors (exact threshold, one LSB beyond, full scale) + random fill.
            xi = [thr, -thr, thr + 1, -thr - 1, 32767, -32768, 0, -1]
            xq = [-thr, thr, -thr - 1, thr + 1, -32768, 32767, -1, 0]
            xi = [max(-32768, min(32767, v)) for v in xi]
            xq = [max(-32768, min(32767, v)) for v in xq]
            xi += [prng.randint(-32768, 32767) for _ in range(200)]
            xq += [prng.randint(-32768, 32767) for _ in range(200)]
            gi, gq = self.run_clip(xi, xq, thr)
            ri, rq = clipper_model(xi, xq, thr)
            self.assertTrue(np.array_equal(gi, ri), f"I mismatch thr={thr}")
            self.assertTrue(np.array_equal(gq, rq), f"Q mismatch thr={thr}")

if __name__ == "__main__":
    unittest.main()
