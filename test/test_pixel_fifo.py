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

from litex.soc.interconnect import stream

from litedsp.common           import pixel_layout
from litedsp.image.stream     import LiteDSPPixelFIFO
from litedsp.image.linebuffer import LiteDSPLineBuffer
from litedsp.stream.split     import LiteDSPSplit

from test.common import run_frames, column

class BranchJoin(LiteXModule):
    """Split -> {line buffer | pixel FIFO} -> lock-step join: the FIFO branch must run P * width
    beats ahead of the 2-D branch, which is exactly what the FIFO provides."""
    def __init__(self, width, depth):
        self.split = LiteDSPSplit(2, layout=pixel_layout(8, 1))
        self.lb    = LiteDSPLineBuffer(kernel_size=3, width=width, with_csr=False)
        self.fifo  = LiteDSPPixelFIFO(depth=depth, n_channels=1, with_csr=False)
        self.sink   = self.split.sink
        self.source = stream.Endpoint([("centre", 8), ("delayed", 8), ("eol", 1)])
        self.comb += [
            self.split.sources[0].connect(self.lb.sink),
            self.split.sources[1].connect(self.fifo.sink),
            self.source.valid.eq(self.lb.source.valid & self.fifo.source.valid),
            self.lb.source.ready.eq(self.source.ready & self.fifo.source.valid),
            self.fifo.source.ready.eq(self.source.ready & self.lb.source.valid),
            self.source.centre.eq(self.lb.source.w11), self.source.delayed.eq(self.fifo.source.data),
            self.source.eol.eq(self.lb.source.eol),
            self.source.first.eq(self.lb.source.first), self.source.last.eq(self.lb.source.last),
        ]

class TestPixelFIFO(unittest.TestCase):
    # verify-tier: model — 16 x 12 frames through Split -> {LineBuffer | PixelFIFO(64)} -> join
    # under backpressure: no deadlock, the window centre equals the FIFO-delayed pixel beat for
    # beat with the framing intact; the FIFO alone is a bit-exact elastic passthrough; latency 0.
    def test_branch_join_and_passthrough(self):
        prng = random.Random(4)
        imgs = [np.array([[prng.randint(0, 255) for _ in range(16)] for _ in range(12)]) for _ in range(2)]
        top  = BranchJoin(16, 64)
        cap  = run_frames(top, imgs, 2*16*12, 1, source_fields=["centre", "delayed", "eol", "first", "last"],
            sink_throttle=0.2, source_ready_rate=0.7)
        flat = np.concatenate([i.reshape(-1) for i in imgs])
        self.assertEqual(column(cap, "centre").tolist(), flat.tolist())
        self.assertEqual(column(cap, "delayed").tolist(), flat.tolist())
        self.assertEqual(column(cap, "first").tolist(), [int(k % 192 == 0) for k in range(384)])
        dut = LiteDSPPixelFIFO(depth=16, n_channels=3, with_csr=False)
        rgb = [np.array([[[prng.randint(0, 255) for _ in range(3)] for _ in range(8)] for _ in range(4)])]
        cap = run_frames(dut, rgb, 32, 3, sink_throttle=0.3, source_ready_rate=0.5)
        for f in ("r", "g", "b"):
            self.assertEqual(column(cap, f).tolist(), rgb[0][:, :, "rgb".index(f)].reshape(-1).tolist())
        self.assertEqual(column(cap, "eol").tolist(), [int(k % 8 == 7) for k in range(32)])
        self.assertEqual(column(cap, "last").tolist(), [int(k == 31) for k in range(32)])
        self.assertEqual(dut.latency, 0)
        with self.assertRaises(ValueError):
            LiteDSPPixelFIFO(depth=1, with_csr=False)

if __name__ == "__main__":
    unittest.main()
