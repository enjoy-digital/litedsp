#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.image.rank  import LiteDSPRankFilter
from litedsp.image.point import LiteDSPThreshold, LiteDSPPixelGain

from test.common import run_frames, beats_to_image, column
from test.models import rank_filter_model, threshold_model, pixel_gain_model

def images(n, w, h, nc, seed):
    prng = random.Random(seed)
    shape = (h, w) if nc == 1 else (h, w, 3)
    return [np.array([prng.randint(0, 255) for _ in range(int(np.prod(shape)))]).reshape(shape)
        for _ in range(n)]

class TestRankFilter(unittest.TestCase):
    # verify-tier: model — ranks 0 / 4 / 8 (mono) and the median on RGB over 16 x 12 frames under
    # backpressure: bit-exact; pinned latency.
    def test_bit_exact(self):
        for rank, nc in ((0, 1), (4, 1), (8, 1), (4, 3)):
            with self.subTest(rank=rank, nc=nc):
                imgs = images(2, 16, 12, nc, seed=rank + nc)
                dut  = LiteDSPRankFilter(n_channels=nc, rank=rank, width=16, with_csr=False)
                cap  = run_frames(dut, imgs, 2*192, nc, sink_throttle=0.2, source_ready_rate=0.7)
                for k, img in enumerate(imgs):
                    self.assertTrue(np.array_equal(beats_to_image(cap[k*192:], 16, 12, nc),
                                                   rank_filter_model(img, rank)), f"frame {k}")
                self.assertEqual(column(cap, "last").tolist(),
                                 [int(k % 192 == 191) for k in range(384)])
                self.assertEqual(dut.latency, dut.lb.latency + 4)

    # verify-tier: bound — the median removes isolated salt-and-pepper pixels from a flat image,
    # erosion shrinks a 4x4 square to 2x2 and dilation grows it to 6x6; a runtime rank change;
    # bypass; invalid rank.
    def test_morphology(self):
        flat = np.full((12, 16), 100, np.int64)
        noisy = flat.copy(); noisy[3, 5] = 255; noisy[7, 9] = 0
        dut = LiteDSPRankFilter(width=16, with_csr=False)
        self.assertTrue(np.array_equal(beats_to_image(run_frames(
            dut, [noisy], 192, 1, sink_throttle=0.0, source_ready_rate=1.0), 16, 12), flat))
        square = np.zeros((12, 16), np.int64); square[4:8, 6:10] = 255
        er = beats_to_image(run_frames(LiteDSPRankFilter(rank=0, width=16, with_csr=False), [
            square], 192, 1, sink_throttle=0.0, source_ready_rate=1.0), 16, 12)
        self.assertEqual(int((er == 255).sum()), 4)
        self.assertTrue(np.all(er[5:7, 7:9] == 255))
        di = beats_to_image(run_frames(LiteDSPRankFilter(rank=8, width=16, with_csr=False), [
            square], 192, 1, sink_throttle=0.0, source_ready_rate=1.0), 16, 12)
        self.assertEqual(int((di == 255).sum()), 36)
        dut = LiteDSPRankFilter(rank=0, width=16, with_csr=False)
        def change():
            for _ in range(250):
                yield
            yield dut.rank.eq(8)
        cap = run_frames(dut, [square, square], 384, 1, sink_throttle=0.0, source_ready_rate=1.0,
                         extra=[change()])
        self.assertEqual(int((beats_to_image(cap, 16, 12) == 255).sum()), 4)
        self.assertEqual(int((beats_to_image(cap[192:], 16, 12) == 255).sum()), 36)
        dut = LiteDSPRankFilter(width=16, with_csr=False)
        dut.bypass.reset = 1
        img = images(1, 16, 12, 1, 3)[0]
        self.assertTrue(np.array_equal(beats_to_image(run_frames(dut, [img], 192, 1), 16, 12), img))
        with self.assertRaises(ValueError):
            LiteDSPRankFilter(rank=9, width=16, with_csr=False)

class TestThreshold(unittest.TestCase):
    # verify-tier: model — random frames with hysteresis (high 160, low 96), a plain threshold and
    # the inverted output, bit-exact under backpressure; latency 1; no chatter on a noisy ramp
    # between the levels; invalid levels.
    def test_bit_exact_and_hysteresis(self):
        imgs = images(2, 16, 12, 1, 11)
        for high, low, inv in ((160, 96, 0), (128, None, 0), (200, 100, 1)):
            with self.subTest(high=high, low=low, invert=inv):
                dut = LiteDSPThreshold(high=high, low=low, invert=bool(inv), with_csr=False)
                cap = run_frames(dut, imgs, 384, 1, sink_throttle=0.2, source_ready_rate=0.7)
                for k, img in enumerate(imgs):
                    self.assertTrue(np.array_equal(beats_to_image(
                        cap[k*192:], 16, 12), threshold_model(img, high, low, inv)), f"frame {k}")
                self.assertEqual(dut.latency, 1)
        prng = random.Random(2)
        ramp = np.array(
            [[min(255, 20*x + prng.randint(-15, 15)) for x in range(16)] for _ in range(4)])
        ramp[:, 0] = 0
        dut = LiteDSPThreshold(high=160, low=96, with_csr=False)
        y = beats_to_image(run_frames(dut, [ramp], 64, 1, sink_throttle=0.0, source_ready_rate=1.0),
                           16, 4)
        for row in y:
            self.assertEqual(int(np.sum(np.abs(np.diff(row)) > 0)), 1)  # One transition per line.
        for kwargs in ({"high": 100, "low": 120}, {"high": 256}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPThreshold(with_csr=False, **kwargs)

class TestPixelGain(unittest.TestCase):
    # verify-tier: model — RGB and mono frames with per-channel gains / offsets, bit-exact under
    # backpressure; unity passes through; gain 2.0 saturates (sticky flag); bypass; invalid frac.
    def test_bit_exact(self):
        imgs = images(2, 16, 12, 3, 12)
        gains, offsets = (300, 256, 180), (-10, 0, 25)
        dut = LiteDSPPixelGain(with_csr=False)
        for c in range(3):
            dut.gain[c].reset, dut.offset[c].reset = gains[c], offsets[c]
        cap = run_frames(dut, imgs, 384, 3, sink_throttle=0.2, source_ready_rate=0.7,
                         extra=[self._sat(dut)])
        for k, img in enumerate(imgs):
            ref, _ = pixel_gain_model(img, gains, offsets)
            self.assertTrue(np.array_equal(beats_to_image(cap[k*192:], 16, 12, 3), ref),
                            f"frame {k}")
        self.assertEqual(dut.latency, 2)
        mono = images(1, 16, 12, 1, 13)
        dut = LiteDSPPixelGain(n_channels=1, with_csr=False)
        self.assertTrue(
            np.array_equal(beats_to_image(run_frames(dut, mono, 192, 1), 16, 12), mono[0]))
        dut = LiteDSPPixelGain(n_channels=1, with_csr=False)
        dut.gain[0].reset = 512
        run_frames(dut, mono, 192, 1, sink_throttle=0.0, source_ready_rate=1.0,
                   extra=[self._sat(dut)])
        self.assertEqual(self.sat, 1)
        dut = LiteDSPPixelGain(n_channels=1, with_csr=False)
        dut.gain[0].reset = 512
        dut.bypass.reset = 1
        self.assertTrue(
            np.array_equal(beats_to_image(run_frames(dut, mono, 192, 1), 16, 12), mono[0]))
        with self.assertRaises(ValueError):
            LiteDSPPixelGain(gain_frac=11, with_csr=False)

    def _sat(self, dut):
        @passive
        def gen():
            while True:
                self.sat = (yield dut.sat)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
