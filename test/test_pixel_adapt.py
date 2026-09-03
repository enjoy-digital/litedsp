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

from litedsp.image.adapt import LiteDSPPixelPack, LiteDSPPixelUnpack, FORMATS

from test.common import run_stream, raster_beats, beats_to_image, column

class PackUnpack(LiteXModule):
    def __init__(self, fmt, width):
        self.pack   = LiteDSPPixelPack(format=fmt)
        self.unpack = LiteDSPPixelUnpack(format=fmt, width=width, with_csr=False)
        self.sink, self.source = self.pack.sink, self.unpack.source
        self.comb += self.pack.source.connect(self.unpack.sink)

class TestPixelAdapt(unittest.TestCase):
    # verify-tier: model — 16 x 12 random frames through pack -> unpack for every format under
    # backpressure: pixels identical (rgb565 keeps the top 5/6/5 bits), framing regenerated.
    def test_round_trip(self):
        prng = random.Random(1)
        for fmt in FORMATS:
            nc = 1 if fmt == "mono" else 3
            with self.subTest(format=fmt):
                img = np.array([[[prng.randint(0, 255) for _ in range(3)] for _ in range(16)] for _ in range(12)])
                if nc == 1:
                    img = img[:, :, 0]
                beats  = raster_beats(img, nc) + raster_beats(img[::-1], nc)
                fields = (["data"] if nc == 1 else ["r", "g", "b"]) + ["eol", "first", "last"]
                dut = PackUnpack(fmt, 16)
                cap = run_stream(dut, beats, 2*16*12, fields, fields, sink_throttle=0.2, source_ready_rate=0.7)
                ref = img.copy()
                if fmt == "rgb565":
                    ref = ref & np.array([0xF8, 0xFC, 0xF8])
                self.assertTrue(np.array_equal(beats_to_image(cap, 16, 12, nc), ref))
                self.assertTrue(np.array_equal(beats_to_image(cap[16*12:], 16, 12, nc), ref[::-1]))
                for f in ("eol", "first", "last"):
                    self.assertEqual(column(cap, f).tolist(), [b[f] for b in beats], f)
                self.assertEqual(dut.pack.latency + dut.unpack.latency, 1)

    def test_words_and_invalid(self):
        dut = LiteDSPPixelPack(format="xrgb8888")
        cap = run_stream(dut, [{"r": 0x11, "g": 0x22, "b": 0x33, "eol": 1}], 1, ["r", "g", "b", "eol"], ["data"])
        self.assertEqual(cap[0]["data"], 0x00112233)
        dut = LiteDSPPixelPack(format="rgb565")
        cap = run_stream(dut, [{"r": 0xFF, "g": 0x00, "b": 0xFF, "eol": 0}], 1, ["r", "g", "b", "eol"], ["data"])
        self.assertEqual(cap[0]["data"], 0xF81F)
        for kwargs in ({"format": "yuyv"}, {"format": "rgb565", "data_width": 10}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPPixelPack(**kwargs)
        with self.assertRaises(ValueError):
            LiteDSPPixelUnpack(width=1, with_csr=False)

if __name__ == "__main__":
    unittest.main()
