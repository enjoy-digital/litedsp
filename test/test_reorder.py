#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.analysis.fft     import LiteDSPFFT
from litedsp.analysis.reorder import LiteDSPBitReverse

from test.common import run_stream, column
from test.models import bit_reverse_model, fft_fixed_model

class TestBitReverse(unittest.TestCase):
    # verify-tier: model — four 16-beat frames reordered bit-exactly under backpressure, with and
    # without the upstream-FFT fill skip; framing on every emitted frame.
    def test_bit_exact(self):
        prng = random.Random(1)
        for skip in (0, 5):
            with self.subTest(fft_latency=skip):
                n = skip + 4*16
                beats = [{"i": prng.randint(-30000, 30000), "q": prng.randint(-30000, 30000)} for _ in range(n)]
                dut = LiteDSPBitReverse(N=16, data_width=16, fft_latency=skip, with_csr=False)
                cap = run_stream(dut, beats, 4*16, ["i", "q"], ["i", "q", "first", "last"],
                    sink_throttle=0.2, source_ready_rate=0.7)
                ref = bit_reverse_model([[b["i"] for b in beats[skip:]], [b["q"] for b in beats[skip:]]], 16)
                self.assertTrue(np.array_equal(column(cap, "i", 16), ref[0]))
                self.assertTrue(np.array_equal(column(cap, "q", 16), ref[1]))
                self.assertEqual(column(cap, "first").tolist(), [int(k % 16 == 0) for k in range(64)])
                self.assertEqual(column(cap, "last").tolist(), [int(k % 16 == 15) for k in range(64)])
        self.assertIsNone(dut.latency)

    # verify-tier: model — FFT followed by the reorder equals the FFT model in natural order.
    def test_fft_natural_order(self):
        class Top(LiteXModule):
            def __init__(self):
                self.fft = LiteDSPFFT(16, data_width=16, with_csr=False)
                self.rev = LiteDSPBitReverse(N=16, data_width=16, fft_latency=self.fft.latency, with_csr=False)
                self.comb += self.fft.source.connect(self.rev.sink)
                self.sink, self.source = self.fft.sink, self.rev.source
        prng  = random.Random(2)
        # Four frames in, three checked: the SDF pipeline releases a frame's tail only as the
        # next frame's samples arrive.
        beats = [{"i": prng.randint(-20000, 20000), "q": prng.randint(-20000, 20000)} for _ in range(4*16)]
        top   = Top()
        cap   = run_stream(top, beats, 3*16, ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        gi, gq = column(cap, "i", 16), column(cap, "q", 16)
        for f in range(3):
            ri, rq = fft_fixed_model([b["i"] for b in beats[16*f:16*f + 16]], [b["q"] for b in beats[16*f:16*f + 16]])
            ni, nq = bit_reverse_model([ri, rq], 16)
            self.assertTrue(np.array_equal(gi[16*f:16*f + 16], ni))
            self.assertTrue(np.array_equal(gq[16*f:16*f + 16], nq))

    def test_invalid(self):
        for kwargs in ({"N": 100}, {"N": 1}, {"fft_latency": -1}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPBitReverse(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
