#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.image.edge import LiteDSPSobel

from test.common import run_frames, beats_to_image, column
from test.models import sobel_model

def images(n, w, h, seed):
    prng = random.Random(seed)
    return [np.array([[prng.randint(0, 255) for _ in range(w)] for _ in range(h)])
                                                                              for _ in range(n)]

class TestSobel(unittest.TestCase):
    # verify-tier: model — 16 x 12 random frames for the three magnitudes (with the direction
    # field on the L1 case) under backpressure: bit-exact with the framing; pinned latency.
    def test_bit_exact(self):
        for mode, with_dir in (("l1", True), ("linf", False), ("approx", False)):
            with self.subTest(mode=mode):
                imgs = images(2, 16, 12, seed=len(mode))
                dut  = LiteDSPSobel(width=16, mode=mode, with_direction=with_dir, with_csr=False)
                fields = ["data", "eol", "first", "last"] + (["direction"] if with_dir else [])
                cap = run_frames(dut, imgs, 2*192, 1, source_fields=fields, sink_throttle=0.2,
                                 source_ready_rate=0.7)
                for k, img in enumerate(imgs):
                    ref = sobel_model(img, mode, 3, "replicate", with_direction=with_dir)
                    mag, direction = ref if with_dir else (ref, None)
                    self.assertTrue(np.array_equal(beats_to_image(cap[k*192:], 16, 12), mag),
                                    f"frame {k}")
                    if with_dir:
                        self.assertTrue(np.array_equal(
                            beats_to_image(cap[k*192:], 16, 12, field="direction"), direction))
                self.assertEqual(column(cap, "eol").tolist(),
                                 [int(k % 16 == 15) for k in range(384)])
                self.assertEqual(dut.latency, dut.lb.latency + 3)

    # verify-tier: bound — a vertical step edge gives 4 * step >> shift on the two edge columns
    # with direction 2 (and a horizontal one direction 0); a 45-degree ramp gives direction 1;
    # bypass passes the input; invalid parameters.
    def test_edges_and_bypass(self):
        step = np.zeros((8, 16), np.int64); step[:, 8:] = 40
        dut = LiteDSPSobel(width=16, with_direction=True, with_csr=False)
        cap = run_frames(dut, [step], 128, 1, source_fields=["data", "direction"],
                         sink_throttle=0.0, source_ready_rate=1.0)
        y, d = beats_to_image(cap, 16, 8), beats_to_image(cap, 16, 8, field="direction")
        self.assertTrue(np.all(y[:, 7] == 160 >> 3))
        self.assertTrue(np.all(y[:, 8] == 160 >> 3))
        self.assertTrue(np.all(np.delete(y, [7, 8], axis=1) == 0))
        self.assertTrue(np.all(d[:, 7:9] == 2))
        hstep = np.zeros((8, 16), np.int64); hstep[4:, :] = 40
        # (a module simulates once)
        dut = LiteDSPSobel(width=16, with_direction=True, with_csr=False)
        cap = run_frames(dut, [hstep], 128, 1, source_fields=["data", "direction"],
                         sink_throttle=0.0, source_ready_rate=1.0)
        d = beats_to_image(cap, 16, 8, field="direction")
        self.assertTrue(np.all(d[3:5, :] == 0))
        ramp = np.array([[min(255, 10*(x + y)) for x in range(16)] for y in range(8)])
        dut = LiteDSPSobel(width=16, with_direction=True, with_csr=False)
        cap = run_frames(dut, [ramp], 128, 1, source_fields=["data", "direction"],
                         sink_throttle=0.0, source_ready_rate=1.0)
        d = beats_to_image(cap, 16, 8, field="direction")
        self.assertTrue(np.all(d[2:6, 2:10] == 1))
        dut = LiteDSPSobel(width=16, with_csr=False)
        dut.bypass.reset = 1
        img = images(1, 16, 8, 5)[0]
        cap = run_frames(dut, [img], 128, 1, sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(beats_to_image(cap, 16, 8), img))
        for kwargs in ({"mode": "l2"}, {"shift": 8}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPSobel(width=16, with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
