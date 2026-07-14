#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.rate.dropper import LiteDSPDownsampler, LiteDSPUpsampler

from test.common import run_stream, column
from test.models import decimate_model, interpolate_model

class TestDropper(unittest.TestCase):
    def rand_iq(self, n, seed, amp=20000):
        prng = random.Random(seed)
        return ([prng.randint(-amp, amp) for _ in range(n)],
                [prng.randint(-amp, amp) for _ in range(n)])

    def test_downsample(self):
        for factor in [1, 2, 3, 5]:
            xi, xq = self.rand_iq(240, factor)
            dut = LiteDSPDownsampler(data_width=16, with_csr=False)
            dut.factor.reset = factor
            n_out = len(xi)//factor
            samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
            cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
                sink_throttle=0.2, source_ready_rate=0.6)
            gi = column(cap, "i", 16)
            ri = decimate_model(xi, factor)[:n_out]
            rq = decimate_model(xq, factor)[:n_out]
            self.assertTrue(np.array_equal(gi, ri), f"down I mismatch factor={factor}")
            self.assertTrue(np.array_equal(column(cap, "q", 16), rq), f"down Q mismatch factor={factor}")

    def test_upsample_hold(self):
        for factor in [1, 2, 4]:
            xi, xq = self.rand_iq(80, factor + 10)
            dut = LiteDSPUpsampler(data_width=16, zero_stuff=False, with_csr=False)
            dut.factor.reset = factor
            n_out = len(xi)*factor
            samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
            cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
                sink_throttle=0.2, source_ready_rate=0.6)
            gi = column(cap, "i", 16)
            ri = interpolate_model(xi, factor, mode="repeat")[:n_out]
            self.assertTrue(np.array_equal(gi, ri), f"up-hold mismatch factor={factor}")

    def test_upsample_zero(self):
        for factor in [2, 4]:
            xi, xq = self.rand_iq(80, factor + 20)
            dut = LiteDSPUpsampler(data_width=16, zero_stuff=True, with_csr=False)
            dut.factor.reset = factor
            n_out = len(xi)*factor
            samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
            cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
                sink_throttle=0.2, source_ready_rate=0.6)
            gi = column(cap, "i", 16)
            ri = interpolate_model(xi, factor, mode="zero")[:n_out]
            self.assertTrue(np.array_equal(gi, ri), f"up-zero mismatch factor={factor}")

if __name__ == "__main__":
    unittest.main()
