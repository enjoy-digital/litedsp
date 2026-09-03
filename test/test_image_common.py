#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import *

from litedsp.common       import pixel_layout, window_layout, video_layout, video_timing_layout, clamped, pixel_channels
from litedsp.image.common import LiteDSPPixelCounter

from litex.soc.interconnect import stream

class TestImageLayouts(unittest.TestCase):
    def test_layouts(self):
        self.assertEqual(pixel_layout(8), [("data", 8), ("eol", 1)])
        self.assertEqual([n for n, _ in pixel_layout(10, 3)], ["r", "g", "b", "eol"])
        self.assertEqual(len(window_layout(8, 3, 5)), 26)
        self.assertEqual(window_layout(8, 3, 3)[4], ("w11", 24))
        self.assertEqual(pixel_channels(stream.Endpoint(pixel_layout(8, 3))), 3)
        self.assertEqual(pixel_channels(stream.Endpoint(pixel_layout(8, 1))), 1)
        for bad in ({"data_width": 3}, {"data_width": 17}, {"n_channels": 2}):
            with self.assertRaises(ValueError):
                pixel_layout(**bad)
        with self.assertRaises(ValueError):
            window_layout(8, 1, 4)

    def test_litex_video_layouts(self):
        try:
            from litex.soc.cores.video import video_data_layout, video_timing_layout as litex_timing
        except ImportError:
            self.skipTest("LiteX video core not importable")
        self.assertEqual(video_layout(8), video_data_layout)
        self.assertEqual(video_timing_layout(12), litex_timing)

class TestPixelCounter(unittest.TestCase):
    # verify-tier: model — a 5x3 frame then a 4x2 frame (first re-synchronises), coordinates per
    # beat, learned width / height, an unframed stream counts from reset.
    def test_coordinates_and_geometry(self):
        dut = LiteDSPPixelCounter(coord_bits=8)
        seen = []
        def frame(w, h):
            for y in range(h):
                for x in range(w):
                    # Inputs take effect after the yield; the coordinates are then read for this
                    # beat before the next edge registers it.
                    yield dut.xfer.eq(1); yield dut.first.eq(int(x == 0 and y == 0)); yield dut.eol.eq(int(x == w - 1)); yield dut.last.eq(int(x == w - 1 and y == h - 1))
                    yield
                    seen.append(((yield dut.col), (yield dut.row)))
            yield dut.xfer.eq(0)
            yield
        def gen():
            yield from frame(5, 3)
            self.w1, self.h1 = (yield dut.width), (yield dut.height)
            yield from frame(4, 2)
            self.w2, self.h2 = (yield dut.width), (yield dut.height)
            self.valid = ((yield dut.width_valid), (yield dut.height_valid))
        run_simulation(dut, gen())
        expect = [(x, y) for y in range(3) for x in range(5)] + [(x, y) for y in range(2) for x in range(4)]
        self.assertEqual(seen, expect)
        self.assertEqual((self.w1, self.h1, self.w2, self.h2), (5, 3, 4, 2))
        self.assertEqual(self.valid, (1, 1))
        dut = LiteDSPPixelCounter(coord_bits=8)
        cols = []
        def unframed():
            for k in range(7):
                yield dut.xfer.eq(1); yield dut.eol.eq(int(k % 3 == 2))
                yield
                cols.append(((yield dut.col), (yield dut.row)))
        run_simulation(dut, unframed())
        self.assertEqual(cols, [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1), (0, 2)])

    def test_clamped(self):
        class Top(Module):
            def __init__(self):
                self.x = Signal((10, True)); self.y = Signal(8)
                self.comb += self.y.eq(clamped(self.x, 8))
        top = Top()
        out = []
        def gen():
            for v in (-5, 0, 100, 255, 256, 511, -512):
                yield top.x.eq(v)
                yield
                out.append((yield top.y))
        run_simulation(top, gen())
        self.assertEqual(out, [0, 0, 100, 255, 255, 255, 0])

if __name__ == "__main__":
    unittest.main()
