#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPDelay tests, bit-exact: the delay pipe shifts data and valid together, so the valid
sample sequence is the identity for any depth — under bubbles/backpressure the delay only
shows up in cycle alignment, never in sample values or order.

verify-tier: model
"""

import random
import unittest

import numpy as np

from litedsp.stream.delay import LiteDSPDelay

from test.common import run_stream, column

class TestDelay(unittest.TestCase):
    def run_delay(self, xi, xq, depth, n_out=None, **kwargs):
        dut = LiteDSPDelay(depth=depth, data_width=16)
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
            len(xi) if n_out is None else n_out, ["i", "q"], ["i", "q"], **kwargs)
        return column(cap, "i", 16), column(cap, "q", 16)

    def test_bit_exact(self):
        # Identity on the sample stream for all depths, under default randomized
        # throttle/backpressure and under the extremes (ready_rate=0.3, throttle=0.4).
        for depth in [0, 1, 5]:
            for kwargs in [{}, {"sink_throttle": 0.4, "source_ready_rate": 0.3}]:
                prng = random.Random(depth)
                xi = [prng.randint(-32768, 32767) for _ in range(80)]
                xq = [prng.randint(-32768, 32767) for _ in range(80)]
                gi, gq = self.run_delay(xi, xq, depth, **kwargs)
                self.assertTrue(np.array_equal(gi, xi), f"I mismatch depth={depth} {kwargs}")
                self.assertTrue(np.array_equal(gq, xq), f"Q mismatch depth={depth} {kwargs}")

    def test_aligns(self):
        # Functional intent: with a gap-free stream the block is a pure `depth`-cycle delay.
        depth = 5
        prng  = random.Random(4)
        xi = [prng.randint(-1000, 1000) for _ in range(80)]
        gi, _ = self.run_delay(xi, [0]*len(xi), depth, n_out=len(xi) - depth,
            sink_throttle=0.0, source_ready_rate=1.0)
        self.assertTrue(np.array_equal(gi, np.array(xi[:len(gi)])))  # No bubbles -> pure delay.

if __name__ == "__main__":
    unittest.main()
