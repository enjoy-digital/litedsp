#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.image.linebuffer import LiteDSPLineBuffer, BORDERS

from test.common import run_frames, column
from test.models import line_buffer_model

def images(n, w, h, nc, seed):
    prng = random.Random(seed)
    shape = (h, w) if nc == 1 else (h, w, 3)
    return [np.array([prng.randint(0, 255) for _ in range(int(np.prod(shape)))]).reshape(shape) for _ in range(n)]

class TestLineBuffer(unittest.TestCase):
    def _check(self, cap, imgs, K, border, w, h):
        n = w*h
        fields = [f"w{i}{j}" for i in range(K) for j in range(K)] + ["eol", "first", "last"]
        for k, img in enumerate(imgs):
            ref = line_buffer_model(img, K, border)
            for f in fields:
                self.assertEqual(column(cap[k*n:(k + 1)*n], f).tolist(), ref[f].tolist(), f"frame {k} {f}")

    # verify-tier: model — two 16 x 12 frames through 3 x 3 (mono, three borders) and 5 x 5 (RGB,
    # mirror) windows under backpressure: every window field and the framing bit-exact against
    # the padded-image model; pinned latency.
    def test_bit_exact(self):
        cases = [(3, "replicate", 1), (3, "mirror", 1), (3, "zero", 1), (5, "mirror", 3), (5, "replicate", 1)]
        for K, border, nc in cases:
            with self.subTest(K=K, border=border, nc=nc):
                imgs = images(2, 16, 12, nc, seed=K + len(border))
                dut  = LiteDSPLineBuffer(n_channels=nc, kernel_size=K, width=16, border=border, with_csr=False)
                fields = [f"w{i}{j}" for i in range(K) for j in range(K)] + ["eol", "first", "last"]
                cap = run_frames(dut, imgs, 2*16*12, nc, source_fields=fields, sink_throttle=0.2, source_ready_rate=0.7)
                self._check(cap, imgs, K, border, 16, 12)
                self.assertEqual(dut.latency, (K//2)*(16 + K//2) + K//2 + 3)

    # verify-tier: bound — a 12-wide frame after a 16-wide one re-learns the width (no error); a
    # line beyond max_width sets the sticky geometry error; the declared latency matches the
    # first output's cycle at full rate; invalid parameters.
    def test_geometry_and_latency(self):
        dut  = LiteDSPLineBuffer(kernel_size=3, width=16, max_width=20, with_csr=False)
        imgs = images(1, 16, 6, 1, 7) + images(1, 12, 6, 1, 8)
        fields = [f"w{i}{j}" for i in range(3) for j in range(3)] + ["eol", "first", "last"]
        cap = run_frames(dut, imgs, 16*6 + 12*6, 1, source_fields=fields, sink_throttle=0.0, source_ready_rate=1.0,
            extra=[self._status(dut)])
        ref0 = line_buffer_model(imgs[0], 3, "replicate")
        ref1 = line_buffer_model(imgs[1], 3, "replicate")
        self.assertEqual(column(cap[:96], "w11").tolist(), ref0["w11"].tolist())
        self.assertEqual(column(cap[96:], "w11").tolist(), ref1["w11"].tolist())
        self.assertEqual(column(cap[96:], "eol").tolist(), ref1["eol"].tolist())
        self.assertEqual(self.err, 0)
        self.assertEqual(self.length, 12)
        dut = LiteDSPLineBuffer(kernel_size=3, width=16, max_width=16, with_csr=False)
        run_frames(dut, images(1, 24, 4, 1, 9), 1, 1, source_fields=fields, sink_throttle=0.0, source_ready_rate=1.0,
            extra=[self._status(dut)])
        self.assertEqual(self.err, 1)
        # Latency: cycles from the first accepted pixel to the first output at full rate.
        dut = LiteDSPLineBuffer(kernel_size=3, width=16, with_csr=False)
        self.first_in = self.first_out = None
        run_frames(dut, images(1, 16, 4, 1, 10), 1, 1, source_fields=fields, sink_throttle=0.0, source_ready_rate=1.0,
            extra=[self._timing(dut)])
        self.assertEqual(self.first_out - self.first_in, dut.latency)
        for kwargs in ({"kernel_size": 4}, {"width": 2}, {"border": "wrap"}, {"width": 32, "max_width": 16}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPLineBuffer(with_csr=False, **kwargs)

    def _status(self, dut):
        @passive
        def gen():
            while True:
                self.err = (yield dut.geometry_error)
                self.length = (yield dut.line_length)
                yield
        return gen()

    def _timing(self, dut):
        @passive
        def gen():
            cyc = 0
            while True:
                if self.first_in is None and (yield dut.sink.valid) and (yield dut.sink.ready):
                    self.first_in = cyc
                if self.first_out is None and (yield dut.source.valid):
                    self.first_out = cyc
                cyc += 1
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
