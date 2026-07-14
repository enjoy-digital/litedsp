#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Stream-op tests, bit-exact against the ops models (conjugate/swap/negate/IQ add), with
explicit saturation and -full-scale wrap edge vectors.

verify-tier: model
"""

import random
import unittest

import numpy as np

from migen import run_simulation

from litedsp.stream.ops import LiteDSPConjugate, LiteDSPSwapIQ, LiteDSPNegate, LiteDSPIQAdd

from test.common import run_stream, column, stream_driver, stream_capture
from test.models import conjugate_model, swap_iq_model, negate_model, iq_add_model

class TestStreamOps(unittest.TestCase):
    def run_op(self, cls, xi, xq):
        dut = cls(data_width=16)
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))], len(xi),
            ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        return column(cap, "i", 16), column(cap, "q", 16)

    def test_ops(self):
        prng = random.Random(2)
        # Random fill + edge vectors: the unary ops have no saturation, so negating the most
        # negative value (-32768) wraps back to -32768 (16-bit two's-complement truncation).
        xi = [-32768, 32767, -32768, 0] + [prng.randint(-32768, 32767) for _ in range(100)]
        xq = [-32768, -32768, 32767, 0] + [prng.randint(-32768, 32767) for _ in range(100)]
        for cls, model in [(LiteDSPConjugate, conjugate_model),
                           (LiteDSPSwapIQ,    swap_iq_model),
                           (LiteDSPNegate,    negate_model)]:
            gi, gq = self.run_op(cls, xi, xq)
            ri, rq = model(xi, xq)
            self.assertTrue(np.array_equal(gi, ri), f"{cls.__name__} I mismatch")
            self.assertTrue(np.array_equal(gq, rq), f"{cls.__name__} Q mismatch")

class TestIQAdd(unittest.TestCase):
    def run_add(self, a, b):
        dut = LiteDSPIQAdd(data_width=16)
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink_a, [{"i": i, "q": q} for (i, q) in a], ("i", "q"), throttle=0.2),
            stream_driver(dut.sink_b, [{"i": i, "q": q} for (i, q) in b], ("i", "q"), throttle=0.3,
                seed=5),
            stream_capture(dut.source, cap, len(a), ("i", "q"), ready_rate=0.7),
        ])
        return column(cap, "i", 16), column(cap, "q", 16)

    def check_model(self, a, b, msg):
        gi, gq = self.run_add(a, b)
        ri, rq = iq_add_model([x[0] for x in a], [x[1] for x in a],
                              [x[0] for x in b], [x[1] for x in b])
        self.assertTrue(np.array_equal(gi, ri), f"{msg}: I mismatch")
        self.assertTrue(np.array_equal(gq, rq), f"{msg}: Q mismatch")
        return gi, gq

    def test_sum_saturated(self):
        prng = random.Random(4)
        n = 100
        a = [(prng.randint(-32768, 32767), prng.randint(-32768, 32767)) for _ in range(n)]
        b = [(prng.randint(-32768, 32767), prng.randint(-32768, 32767)) for _ in range(n)]
        self.check_model(a, b, "random")

    def test_saturation_edges(self):
        # Explicit corner vectors: double max-negative (must clamp at -32768, not wrap to 0),
        # double max-positive, exact-boundary sums (no saturation), and one-LSB overflows.
        a = [(-32768, -32768), (32767, 32767), (-32768, 32767), (-32768, -32768),
             (-16384,  16384), (-16385, 16384), (0, 0)]
        b = [(-32768, -32768), (32767, 32767), (-1, 1),         ( 32767,  32767),
             (-16384,  16383), (-16384, 16384), (-32768, 32767)]
        gi, gq = self.check_model(a, b, "edges")
        self.assertTrue(np.array_equal(gi, [-32768, 32767, -32768, -1, -32768, -32768, -32768]))
        self.assertTrue(np.array_equal(gq, [-32768, 32767,  32767, -1,  32767,  32767,  32767]))

if __name__ == "__main__":
    unittest.main()
