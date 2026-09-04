#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest
import itertools

import numpy as np

from migen import *

from litedsp.image.lut    import LiteDSPPixelLUT
from litedsp.image.color  import LiteDSPColorMatrix
from litedsp.image.design import gamma_table, color_preset, contrast_table

from test.common import run_frames, beats_to_image, column
from test.models import pixel_lut_model, color_matrix_model

def images(n, w, h, nc, seed):
    prng = random.Random(seed)
    shape = (h, w) if nc == 1 else (h, w, 3)
    return [np.array([prng.randint(0, 255) for _ in range(int(np.prod(shape)))]).reshape(shape) for _ in range(n)]

class TestPixelLUT(unittest.TestCase):
    # verify-tier: model — the identity table (mono), a gamma 2.2 initialisation (RGB shared),
    # per-channel tables loaded through the port mid-stream (frame 2 onwards), bypass; latency 1.
    def test_tables(self):
        imgs = images(2, 16, 12, 1, 1)
        dut = LiteDSPPixelLUT(n_channels=1, with_csr=False)
        cap = run_frames(dut, imgs, 384, 1, sink_throttle=0.2, source_ready_rate=0.7)
        for k in range(2):
            self.assertTrue(np.array_equal(beats_to_image(cap[k*192:], 16, 12), imgs[k]))
        self.assertEqual(dut.latency, 1)
        rgb = images(2, 16, 12, 3, 2)
        dut = LiteDSPPixelLUT(n_channels=3, gamma=2.2, with_csr=False)
        cap = run_frames(dut, rgb, 384, 3, sink_throttle=0.2, source_ready_rate=0.7)
        table = gamma_table(2.2, 8)
        for k in range(2):
            self.assertTrue(np.array_equal(beats_to_image(cap[k*192:], 16, 12, 3), pixel_lut_model(rgb[k], table)))
        # Per-channel tables loaded through the port while the stream flows (768 writes): the
        # last of six frames uses the new tables.
        tables = [gamma_table(1.8), contrast_table(1.5, 0.05), list(range(255, -1, -1))]
        dut = LiteDSPPixelLUT(n_channels=3, shared=False, with_csr=False)
        def loader():
            for c in range(3):
                yield dut.lut_channel.eq(c)
                yield dut.lut_addr.eq(0)
                for v in tables[c]:
                    yield dut.lut_data.eq(v); yield dut.lut_we.eq(1)
                    yield
            yield dut.lut_we.eq(0)
        frames6 = rgb + images(4, 16, 12, 3, 9)
        cap = run_frames(dut, frames6, 6*192, 3, sink_throttle=0.0, source_ready_rate=1.0, extra=[loader()])
        self.assertTrue(np.array_equal(beats_to_image(cap[5*192:], 16, 12, 3), pixel_lut_model(frames6[5], tables)))
        dut = LiteDSPPixelLUT(n_channels=1, gamma=2.2, with_csr=False)
        dut.bypass.reset = 1
        self.assertTrue(np.array_equal(beats_to_image(run_frames(dut, imgs[:1], 192, 1), 16, 12), imgs[0]))
        with self.assertRaises(ValueError):
            LiteDSPPixelLUT(gamma=0, with_csr=False)

class TestColorMatrix(unittest.TestCase):
    # verify-tier: model — identity, BT.601 / 709 studio both ways, the JPEG pair and the 601 grey
    # on 16 x 12 random frames under backpressure: bit-exact; latency 3.
    def test_bit_exact(self):
        imgs = images(2, 16, 12, 3, 3)
        for name in ("identity", "rgb_to_ycbcr_601", "ycbcr_to_rgb_601", "rgb_to_ycbcr_709", "rgb_to_ycbcr_jpeg", "ycbcr_to_rgb_jpeg", "rgb_to_gray_601"):
            with self.subTest(preset=name):
                c, i, o = color_preset(name)
                n_out = len(c)//3
                dut = LiteDSPColorMatrix(n_out=n_out, coefficients=c, in_offsets=i, out_offsets=o, with_csr=False)
                cap = run_frames(dut, imgs, 384, 3, source_fields=(["data"] if n_out == 1 else ["r", "g", "b"]) + ["eol", "first", "last"],
                    sink_throttle=0.2, source_ready_rate=0.7)
                for k in range(2):
                    ref, _ = color_matrix_model(imgs[k], c, i, o)
                    self.assertTrue(np.array_equal(beats_to_image(cap[k*192:], 16, 12, n_out), ref), f"frame {k}")
                self.assertEqual(column(cap, "eol").tolist(), [int(k % 16 == 15) for k in range(384)])
                self.assertEqual(dut.latency, 3)

    # verify-tier: bound — full-range JPEG round trip within 1 LSB on random pixels and the eight
    # saturated colours (studio 601 within 2 LSB, reported); grey of white is 255 (full) / 235
    # (studio); a reload committed mid-frame lands at the next frame; invalid parameters.
    def test_round_trip_and_commit(self):
        prng = random.Random(4)
        pix  = np.array([[prng.randint(0, 255) for _ in range(3)] for _ in range(64)] + [list(p) for p in itertools.product((0, 255), repeat=3)])
        img  = pix.reshape(8, 9, 3)
        for fwd, inv, tol in (("rgb_to_ycbcr_jpeg", "ycbcr_to_rgb_jpeg", 1), ("rgb_to_ycbcr_601", "ycbcr_to_rgb_601", 2)):
            with self.subTest(pair=fwd):
                c1, i1, o1 = color_preset(fwd); c2, i2, o2 = color_preset(inv)
                y, _ = color_matrix_model(img, c1, i1, o1)
                back, _ = color_matrix_model(y, c2, i2, o2)
                self.assertLessEqual(int(np.max(np.abs(back - img))), tol)
        white = np.full((4, 8, 3), 255)
        for name, expect in (("rgb_to_gray_709", 255), ("rgb_to_ycbcr_601", 235)):
            c, i, o = color_preset(name)
            n_out = len(c)//3
            dut = LiteDSPColorMatrix(n_out=n_out, coefficients=c, in_offsets=i, out_offsets=o, with_csr=False)
            cap = run_frames(dut, [white], 32, 3, source_fields=(["data"] if n_out == 1 else ["r", "g", "b"]), sink_throttle=0.0, source_ready_rate=1.0)
            self.assertEqual(int(cap[0]["data" if n_out == 1 else "r"]), expect)
        imgs = images(2, 16, 8, 3, 5)
        c_id, i_id, o_id = color_preset("identity")
        c_y, i_y, o_y = color_preset("rgb_to_ycbcr_jpeg")
        dut = LiteDSPColorMatrix(coefficients=c_id, in_offsets=i_id, out_offsets=o_id, with_csr=False)
        def loader():
            for _ in range(20):
                yield
            entries = list(c_y) + list(i_y) + list(o_y)
            for k, v in enumerate(entries):
                yield dut.coeff_index.eq(k if k < 9 else (9 + (k - 9) if k < 12 else 12 + (k - 12)))
                yield dut.coeff_value.eq(v); yield dut.coeff_we.eq(1)
                yield
            yield dut.coeff_we.eq(0); yield dut.commit.eq(1)
            yield
            yield dut.commit.eq(0)
        cap = run_frames(dut, imgs, 256, 3, sink_throttle=0.0, source_ready_rate=1.0, extra=[loader()])
        self.assertTrue(np.array_equal(beats_to_image(cap, 16, 8, 3), imgs[0]))
        self.assertTrue(np.array_equal(beats_to_image(cap[128:], 16, 8, 3), color_matrix_model(imgs[1], c_y, i_y, o_y)[0]))
        for kwargs in ({"coefficients": [1]*8}, {"coeff_frac": 16}, {"n_out": 2}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPColorMatrix(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
