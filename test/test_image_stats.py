#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.image.stats     import LiteDSPPixelStats
from litedsp.image.histogram import LiteDSPPixelHistogram

from test.common import run_frames, beats_to_image, column
from test.models import pixel_stats_model, histogram_model

def images(n, w, h, nc, seed):
    prng = random.Random(seed)
    shape = (h, w) if nc == 1 else (h, w, 3)
    return [np.array([prng.randint(0, 255) for _ in range(int(np.prod(shape)))]).reshape(shape) for _ in range(n)]

class TestPixelStats(unittest.TestCase):
    # verify-tier: model — two 16 x 12 RGB frames (channel 1, 4 x 4 zones of 4 x 3) under
    # backpressure: passthrough bit-exact, the statistics latched at each frame's end match the
    # model (frame 1's values visible after its last, frame 0's meanwhile); a ramp's min / max;
    # latency 0.
    def test_stats(self):
        imgs = images(2, 16, 12, 3, 5)
        dut  = LiteDSPPixelStats(n_channels=3, channel=1, zones=4, with_csr=False)
        dut.zone_width.reset, dut.zone_height.reset = 4, 3
        self.seen = []
        cap = run_frames(dut, imgs, 384, 3, sink_throttle=0.2, source_ready_rate=0.7, extra=[self._watch(dut)])
        for k in range(2):
            self.assertTrue(np.array_equal(beats_to_image(cap[k*192:], 16, 12, 3), imgs[k]))
        refs = [pixel_stats_model(img, 1, 4, 4, 3) for img in imgs]
        self.assertEqual(len(self.seen), 2)
        for got, ref in zip(self.seen, refs):
            self.assertEqual(got["sum"], ref["sum"]); self.assertEqual(got["min"], ref["min"]); self.assertEqual(got["max"], ref["max"])
            self.assertEqual(got["count"], ref["count"]); self.assertEqual(got["zones"], ref["zones"])
        self.assertEqual(dut.latency, 0)
        ramp = np.array([[x + 3*y for x in range(16)] for y in range(12)])
        dut = LiteDSPPixelStats(zones=1, with_csr=False)
        self.seen = []
        run_frames(dut, [ramp], 192, 1, sink_throttle=0.0, source_ready_rate=1.0, extra=[self._watch(dut, 300)])
        self.assertEqual((self.seen[0]["min"], self.seen[0]["max"], self.seen[0]["zones"][0]), (0, 48, int(ramp.sum())))
        with self.assertRaises(ValueError):
            LiteDSPPixelStats(zones=3, with_csr=False)

    def _watch(self, dut, cycles=1500):
        def gen():                                                      # Active: outlives the capture
            for _ in range(cycles):                                     # so the last latch is seen.
                if (yield dut.update):
                    zones = []
                    for z in dut.zone:
                        zones.append((yield z))
                    self.seen.append(dict(sum=(yield dut.sum), min=(yield dut.min), max=(yield dut.max), count=(yield dut.count), zones=zones))
                yield
        return gen()

class TestPixelHistogram(unittest.TestCase):
    # verify-tier: model — three frames (16 x 12 mono, 16 bins; 32 x 24 RGB channel 2, 256 bins) under
    # backpressure: the streamed histograms equal np.bincount with bin 0 first / last bin last,
    # frames counted, no overrun; an undrained histogram sets the sticky overrun.
    def test_histograms(self):
        # The drain (one beat per bin) must fit inside a frame: 256 bins need the 32 x 24 frames.
        for nc, ch, bl, w, h in ((1, 0, 4, 16, 12), (3, 2, 8, 32, 24)):
            with self.subTest(nc=nc, bins_log2=bl):
                imgs = images(3, w, h, nc, seed=bl)
                dut  = LiteDSPPixelHistogram(n_channels=nc, channel=ch, bins_log2=bl, with_csr=False)
                cap  = run_frames(dut, imgs, 3*(1 << bl), nc, source_fields=["data", "first", "last"], sink_throttle=0.2, source_ready_rate=0.7,
                    extra=[self._status(dut)])
                nb = 1 << bl
                for k, img in enumerate(imgs):
                    self.assertEqual(column(cap[k*nb:(k + 1)*nb], "data").tolist(), histogram_model(img, ch, bl).tolist(), f"frame {k}")
                self.assertEqual(column(cap, "first").tolist(), [int(k % nb == 0) for k in range(3*nb)])
                self.assertEqual(column(cap, "last").tolist(), [int(k % nb == nb - 1) for k in range(3*nb)])
                self.assertEqual(self.overrun, 0)
                self.assertEqual(self.frames, 3)
                self.assertIsNone(dut.latency)
        imgs = images(3, 16, 12, 1, 9)
        dut  = LiteDSPPixelHistogram(bins_log2=8, with_csr=False)
        run_frames(dut, imgs, 8, 1, source_fields=["data"], sink_throttle=0.0, source_ready_rate=0.02, extra=[self._status(dut)])
        self.assertEqual(self.overrun, 1)
        with self.assertRaises(ValueError):
            LiteDSPPixelHistogram(bins_log2=9, with_csr=False)

    def _status(self, dut):
        @passive
        def gen():
            while True:
                self.overrun = (yield dut.overrun)
                self.frames  = (yield dut.frames)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
