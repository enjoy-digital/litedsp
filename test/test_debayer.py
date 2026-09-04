#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import random
import unittest

import numpy as np

from litedsp.image.debayer import LiteDSPDebayer
from litedsp.image.design  import mosaic, BAYER_PATTERNS

from test.common import run_frames, beats_to_image, column
from test.models import debayer_model

RGB = ["r", "g", "b", "eol", "first", "last"]

class TestDebayer(unittest.TestCase):
    # verify-tier: model — 16 x 12 random mosaics for the four patterns (mirror border) and the
    # replicate border under backpressure: bit-exact RGB with the framing; pinned latency.
    def test_bit_exact(self):
        prng = random.Random(1)
        raws = [np.array([[prng.randint(0, 255) for _ in range(16)] for _ in range(12)])
            for _ in range(2)]
        for pattern, border in [(p, "mirror") for p in BAYER_PATTERNS] + [("rggb", "replicate")]:
            with self.subTest(pattern=pattern, border=border):
                dut = LiteDSPDebayer(pattern=pattern, width=16, border=border, with_csr=False)
                cap = run_frames(dut, raws, 384, 1, source_fields=RGB, sink_throttle=0.2,
                                 source_ready_rate=0.7)
                for k, raw in enumerate(raws):
                    self.assertTrue(np.array_equal(beats_to_image(
                        cap[k*192:], 16, 12, 3), debayer_model(raw, pattern, border)), f"frame {k}")
                self.assertEqual(column(cap, "last").tolist(),
                                 [int(k % 192 == 191) for k in range(384)])
                self.assertEqual(dut.latency, dut.lb.latency + 2)

    # verify-tier: bound — a flat-colour mosaic reconstructs its colour exactly; a mosaiced
    # smooth colour gradient comes back with PSNR >= 40 dB (bilinear is exact on linear ramps); a
    # runtime phase flip on a cropped (shifted)
    # mosaic restores the colours; invalid pattern.
    def test_reconstruction(self):
        flat = np.zeros((12, 16, 3), np.int64); flat[:] = (200, 90, 40)
        dut = LiteDSPDebayer(width=16, with_csr=False)
        out = beats_to_image(run_frames(dut, [mosaic(flat, "rggb")], 192, 1, source_fields=RGB,
                                        sink_throttle=0.0, source_ready_rate=1.0), 16, 12, 3)
        self.assertTrue(np.array_equal(out, flat))
        grad = np.array([[(8*x, 16*y, 255 - 8*x) for x in range(32)] for y in range(12)])
        dut = LiteDSPDebayer(width=32, with_csr=False)
        out = beats_to_image(run_frames(dut, [mosaic(grad, "rggb")], 384, 1, source_fields=RGB,
                                        sink_throttle=0.0, source_ready_rate=1.0), 32, 12, 3)
        mse = float(np.mean((out[1:-1, 1:-1].astype(float) - grad[1:-1, 1:-1])**2))
        self.assertGreaterEqual(10*math.log10(255**2/max(mse, 1e-9)), 40.0)
        shifted = mosaic(flat, "rggb")[:, 1:]                        # Crop one column: phase flips.
        dut = LiteDSPDebayer(width=15, with_csr=False)
        dut.phase.reset = 1
        out = beats_to_image(run_frames(dut, [shifted], 180, 1, source_fields=RGB,
                                        sink_throttle=0.0, source_ready_rate=1.0), 15, 12, 3)
        self.assertTrue(np.array_equal(out, flat[:, 1:]))
        with self.assertRaises(ValueError):
            LiteDSPDebayer(pattern="rgbg", width=16, with_csr=False)

if __name__ == "__main__":
    unittest.main()
