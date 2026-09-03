#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.image.scale import LiteDSPDownscaler, LiteDSPCrop

from test.common import run_frames, beats_to_image, column
from test.models import downscaler_model, crop_model

def images(n, w, h, nc, seed):
    prng = random.Random(seed)
    shape = (h, w) if nc == 1 else (h, w, 3)
    return [np.array([prng.randint(0, 255) for _ in range(int(np.prod(shape)))]).reshape(shape) for _ in range(n)]

def framing(w, h, n_frames):
    n = w*h
    return ([int(k % w == w - 1) for k in range(n*n_frames)], [int(k % n == 0) for k in range(n*n_frames)],
            [int(k % n == n - 1) for k in range(n*n_frames)])

class TestDownscaler(unittest.TestCase):
    # verify-tier: model — 16 x 12 mono by 2 (8 x 6), RGB by 4 (4 x 3) and a 15 x 11 frame with
    # partial tiles by 2 (7 x 5), two frames each under backpressure: bit-exact means and framing;
    # latency 2.
    def test_bit_exact(self):
        for w, h, D, nc in ((16, 12, 2, 1), (16, 12, 4, 3), (15, 11, 2, 1)):
            with self.subTest(w=w, h=h, D=D, nc=nc):
                imgs = images(2, w, h, nc, seed=w + D + nc)
                dut  = LiteDSPDownscaler(n_channels=nc, decimation=D, width=w, height=h, with_csr=False)
                tw, th = w//D, h//D
                cap = run_frames(dut, imgs, 2*tw*th, nc, sink_throttle=0.2, source_ready_rate=0.7)
                for k, img in enumerate(imgs):
                    self.assertTrue(np.array_equal(beats_to_image(cap[k*tw*th:], tw, th, nc), downscaler_model(img, D)), f"frame {k}")
                eol, first, last = framing(tw, th, 2)
                self.assertEqual(column(cap, "eol").tolist(), eol)
                self.assertEqual(column(cap, "first").tolist(), first)
                self.assertEqual(column(cap, "last").tolist(), last)
                self.assertEqual(dut.latency, 2)
        for kwargs in ({"decimation": 3}, {"width": 4, "decimation": 8}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPDownscaler(with_csr=False, **kwargs)

class TestCrop(unittest.TestCase):
    # verify-tier: model — a (3, 2, 8, 6) ROI on 16 x 12 mono and RGB frames under backpressure:
    # bit-exact pixels and regenerated framing; a ROI update committed mid-frame lands at the
    # next frame; a full-frame ROI is the identity; a ROI beyond the frame flags the geometry
    # error; latency 1; invalid parameters.
    def test_roi(self):
        for nc in (1, 3):
            with self.subTest(nc=nc):
                imgs = images(2, 16, 12, nc, seed=nc)
                dut  = LiteDSPCrop(n_channels=nc, x0=3, y0=2, roi_width=8, roi_height=6, with_csr=False)
                cap  = run_frames(dut, imgs, 2*48, nc, sink_throttle=0.2, source_ready_rate=0.7)
                for k, img in enumerate(imgs):
                    self.assertTrue(np.array_equal(beats_to_image(cap[k*48:], 8, 6, nc), crop_model(img, 3, 2, 8, 6)), f"frame {k}")
                eol, first, last = framing(8, 6, 2)
                self.assertEqual(column(cap, "eol").tolist(), eol)
                self.assertEqual(column(cap, "last").tolist(), last)
                self.assertEqual(dut.latency, 1)
        imgs = images(2, 16, 12, 1, 7)
        dut = LiteDSPCrop(n_channels=1, x0=0, y0=0, roi_width=16, roi_height=12, with_csr=False)
        def update():
            for _ in range(30):
                yield
            yield dut.x0.eq(4); yield dut.y0.eq(4); yield dut.roi_width.eq(4); yield dut.roi_height.eq(4)
            yield dut.commit.eq(1)
            yield
            yield dut.commit.eq(0)
        cap = run_frames(dut, imgs, 192 + 16, 1, sink_throttle=0.0, source_ready_rate=1.0, extra=[update()])
        self.assertTrue(np.array_equal(beats_to_image(cap, 16, 12), imgs[0]))
        self.assertTrue(np.array_equal(beats_to_image(cap[192:], 4, 4), crop_model(imgs[1], 4, 4, 4, 4)))
        dut = LiteDSPCrop(n_channels=1, x0=10, y0=0, roi_width=8, roi_height=4, with_csr=False)
        run_frames(dut, imgs[:1], 24, 1, sink_throttle=0.0, source_ready_rate=1.0, extra=[self._status(dut, 250)])
        self.assertEqual(self.err, 1)
        for kwargs in ({"roi_width": 0}, {"x0": 4000, "roi_width": 200}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPCrop(with_csr=False, **kwargs)

    def _status(self, dut, cycles):
        def gen():
            for _ in range(cycles):
                self.err = (yield dut.geometry_error)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
