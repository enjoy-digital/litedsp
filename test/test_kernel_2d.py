#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.image.kernel import LiteDSPKernel2D
from litedsp.image.design import kernel_preset

from test.common import run_frames, beats_to_image, column
from test.models import kernel2d_model

def images(n, w, h, nc, seed):
    prng = random.Random(seed)
    shape = (h, w) if nc == 1 else (h, w, 3)
    return [np.array([prng.randint(0, 255) for _ in range(int(np.prod(shape)))]).reshape(shape) for _ in range(n)]

class TestKernel2D(unittest.TestCase):
    # verify-tier: model — identity, gaussian3 (RGB), sobel_x (with its 128 offset) and gaussian5
    # on 16 x 12 frames under backpressure: bit-exact pixels and framing; pinned latency.
    def test_bit_exact(self):
        for name, nc in (("identity", 1), ("gaussian3", 3), ("sobel_x", 1), ("gaussian5", 1)):
            with self.subTest(preset=name, nc=nc):
                coefficients, shift, offset = kernel_preset(name)
                K = 5 if name == "gaussian5" else 3
                imgs = images(2, 16, 12, nc, seed=len(name))
                dut  = LiteDSPKernel2D(n_channels=nc, kernel_size=K, coefficients=coefficients, shift=shift, offset=offset,
                    width=16, with_csr=False)
                cap = run_frames(dut, imgs, 2*16*12, nc, sink_throttle=0.2, source_ready_rate=0.7)
                for k, img in enumerate(imgs):
                    ref, _ = kernel2d_model(img, coefficients, shift, offset, K, "replicate")
                    self.assertTrue(np.array_equal(beats_to_image(cap[k*192:], 16, 12, nc), ref), f"frame {k}")
                self.assertEqual(column(cap, "eol").tolist(), [int(k % 16 == 15) for k in range(384)])
                self.assertEqual(column(cap, "last").tolist(), [int(k % 192 == 191) for k in range(384)])
                self.assertEqual(dut.latency, dut.lb.latency + 2)

    # verify-tier: bound — Sobel X on a vertical step gives offset +/- 4 * step on the two edge
    # columns only; a Gaussian of a constant image is that constant; a saturating kernel sets the
    # sticky flag.
    def test_edges_constant_saturation(self):
        step = np.zeros((8, 16), np.int64); step[:, 8:] = 20
        c, s, o = kernel_preset("sobel_x")
        dut = LiteDSPKernel2D(coefficients=c, shift=s, offset=o, width=16, with_csr=False)
        y = beats_to_image(run_frames(dut, [step], 128, 1, sink_throttle=0.0, source_ready_rate=1.0), 16, 8)
        self.assertTrue(np.all(y[:, 7] == 128 + 80))                     # (1 + 2 + 1) * 20 on both
        self.assertTrue(np.all(y[:, 8] == 128 + 80))                     # edge columns.
        self.assertTrue(np.all(np.delete(y, [7, 8], axis=1) == 128))
        c, s, o = kernel_preset("gaussian3")
        dut = LiteDSPKernel2D(coefficients=c, shift=s, offset=o, width=16, with_csr=False)
        flat = np.full((6, 16), 173)
        y = beats_to_image(run_frames(dut, [flat], 96, 1, sink_throttle=0.0, source_ready_rate=1.0), 16, 6)
        self.assertTrue(np.all(y == 173))
        c, s, o = kernel_preset("sharpen")
        dut = LiteDSPKernel2D(coefficients=c, shift=s, offset=o, width=16, with_csr=False)
        self.sat = None
        run_frames(dut, [step*12], 128, 1, sink_throttle=0.0, source_ready_rate=1.0, extra=[self._sat(dut)])   # 5 * 240 - 3 * 240 ...
        self.assertEqual(self.sat, 1)                                   # ... clamps at the step.

    # verify-tier: bound — a coefficient reload committed mid-frame lands exactly at the next
    # frame start (frame 1 identity, frame 2 sobel_x); bypass equals the input at the same
    # latency; invalid parameters.
    def test_commit_and_bypass(self):
        imgs = images(2, 16, 8, 1, 21)
        c_id, _, _ = kernel_preset("identity")
        c_sx, s_sx, o_sx = kernel_preset("sobel_x")
        dut = LiteDSPKernel2D(coefficients=c_id, shift=0, offset=0, width=16, with_csr=False)
        def loader():
            for _ in range(80):                                         # Mid frame 0 (row 0 is out).
                yield
            for k, v in enumerate(c_sx):
                yield dut.coeff_index.eq(k); yield dut.coeff_value.eq(v); yield dut.coeff_we.eq(1)
                yield
            yield dut.coeff_we.eq(0)
            yield dut.offset.eq(o_sx)                                   # Offset is a plain runtime knob:
            yield dut.commit.eq(1)                                      # here it changes with the kernel.
            yield
            yield dut.commit.eq(0)
        cap = run_frames(dut, imgs, 2*128, 1, sink_throttle=0.0, source_ready_rate=1.0, extra=[loader()])
        # The offset changes immediately (frame 0 keeps the identity kernel with +128 from then on)
        # so compare frame 1 only for the atomic coefficient switch.
        ref1, _ = kernel2d_model(imgs[1], c_sx, s_sx, o_sx, 3, "replicate")
        self.assertTrue(np.array_equal(beats_to_image(cap[128:], 16, 8), ref1))
        ident = beats_to_image(cap[:128], 16, 8)
        self.assertTrue(np.array_equal(ident[:1], imgs[0][:1]))          # Before the offset write.
        dut = LiteDSPKernel2D(coefficients=c_sx, shift=s_sx, offset=o_sx, width=16, with_csr=False)
        dut.bypass.reset = 1
        cap = run_frames(dut, imgs[:1], 128, 1, sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(beats_to_image(cap, 16, 8), imgs[0]))
        for kwargs in ({"coefficients": [1]*8}, {"shift": 16}, {"coeff_width": 1}, {"coefficients": [600]*9}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPKernel2D(width=16, with_csr=False, **kwargs)

    def _sat(self, dut):
        @passive
        def gen():
            while True:
                self.sat = (yield dut.sat)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
