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

from litedsp.comm.conv_interleaver import (LiteDSPConvolutionalInterleaver,
                                           LiteDSPConvolutionalDeinterleaver)

from test.common import run_stream, column
from test.models import conv_interleaver_model

class TestConvolutionalInterleaver(unittest.TestCase):
    # verify-tier: model — geometries (12,17), (3,2), (2,1), (8,4) on random bytes, interleaver
    # and deinterleaver bit-exact under backpressure; the pair delays by (B-1) depth B symbols;
    # latency 2.
    def test_bit_exact_and_round_trip(self):
        prng = random.Random(7)
        for B, D in ((12, 17), (3, 2), (2, 1), (8, 4)):
            with self.subTest(B=B, D=D):
                n = 2*(B - 1)*D*B + 60
                x = [prng.randint(0, 255) for _ in range(n)]
                il = LiteDSPConvolutionalInterleaver(branches=B, depth=D, with_csr=False)
                cap = run_stream(il, [{"data": v} for v in x], n, ["data"], ["data"],
                                 sink_throttle=0.2, source_ready_rate=0.7)
                y = column(cap, "data").tolist()
                self.assertEqual(y, conv_interleaver_model(x, B, D).tolist())
                dl = LiteDSPConvolutionalDeinterleaver(branches=B, depth=D, with_csr=False)
                cap = run_stream(dl, [{"data": v} for v in y], n, ["data"], ["data"],
                                 sink_throttle=0.2, source_ready_rate=0.7)
                z = column(cap, "data").tolist()
                self.assertEqual(z, conv_interleaver_model(y, B, D, deinterleave=True).tolist())
                d = (B - 1)*D*B
                self.assertEqual(z[d:], x[:n - d])
                self.assertEqual(il.latency, 2)

    # verify-tier: bound — a burst of B corrupted symbols on the interleaved stream lands as
    # single errors at least depth * B - 1 symbols apart after deinterleaving; phase_rst restarts
    # the commutator; bypass; invalid parameters.
    def test_burst_spreading(self):
        B, D = 4, 3
        n = 2*(B - 1)*D*B + 40
        x = list(range(1, n + 1))
        y = conv_interleaver_model(x, B, D).tolist()
        k0 = (B - 1)*D*B + 5
        for k in range(k0, k0 + B):
            y[k] ^= 0xFF
        z = conv_interleaver_model(y, B, D, deinterleave=True).tolist()
        d = (B - 1)*D*B
        errs = [k for k in range(d, n) if z[k] != x[k - d]]
        self.assertEqual(len(errs), B)
        self.assertGreaterEqual(int(np.min(np.diff(errs))), D*B - 1)
        dut = LiteDSPConvolutionalInterleaver(branches=3, depth=2, with_csr=False)
        beats = [{"data": v} for v in range(1, 25)]
        def rst():
            for _ in range(12):
                yield
            yield dut.phase_rst.eq(1)
            yield
            yield dut.phase_rst.eq(0)
        cap = run_stream(dut, beats, 24, ["data"], ["data"], sink_throttle=0.0,
                         source_ready_rate=1.0, extra=[rst()])
        self.assertNotEqual(column(cap, "data").tolist(),
                            conv_interleaver_model(range(1, 25), 3, 2).tolist())
        dut = LiteDSPConvolutionalInterleaver(with_csr=False)
        dut.bypass.reset = 1
        cap = run_stream(dut, beats, 24, ["data"], ["data"])
        self.assertEqual(column(cap, "data").tolist(), list(range(1, 25)))
        for kwargs in ({"branches": 1}, {"depth": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPConvolutionalInterleaver(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
