#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPSkidBuffer tests, bit-exact: elastic buffer, identity on the sample stream (no
loss, duplication, or reordering) under randomized and extreme throttle/backpressure.

verify-tier: model
"""

import random
import unittest

import numpy as np

from litedsp.stream.buffer import LiteDSPSkidBuffer

from test.common import run_stream, column

class TestSkidBuffer(unittest.TestCase):
    def run_skid(self, data, **kwargs):
        dut = LiteDSPSkidBuffer(data_width=16)
        cap = run_stream(dut, data, len(data), ["i", "q"], ["i", "q"], **kwargs)
        return column(cap, "i", 16), column(cap, "q", 16)

    def test_bit_exact(self):
        # Identity under default randomized backpressure, the extremes (ready_rate=0.3,
        # throttle=0.4), and full-rate streaming (skid must sustain 100% throughput paths).
        for kwargs in [{},
                       {"sink_throttle": 0.4, "source_ready_rate": 0.3},
                       {"sink_throttle": 0.0, "source_ready_rate": 1.0}]:
            prng = random.Random(2)
            data = [{"i": prng.randint(-32768, 32767), "q": prng.randint(-32768, 32767)}
                    for _ in range(120)]
            gi, gq = self.run_skid(data, **kwargs)
            self.assertTrue(np.array_equal(gi, [d["i"] for d in data]), f"I mismatch {kwargs}")
            self.assertTrue(np.array_equal(gq, [d["q"] for d in data]), f"Q mismatch {kwargs}")

if __name__ == "__main__":
    unittest.main()
