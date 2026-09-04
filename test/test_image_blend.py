#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.image.blend   import LiteDSPAlphaBlend
from litedsp.image.overlay import LiteDSPBoxOverlay

from test.common import run_frames, raster_beats, beats_to_image, column
from test.models import alpha_blend_model, box_overlay_model

def images(n, w, h, nc, seed):
    prng = random.Random(seed)
    shape = (h, w) if nc == 1 else (h, w, 3)
    return [np.array([prng.randint(0, 255) for _ in range(int(np.prod(shape)))]).reshape(shape)
        for _ in range(n)]

def simulate_join(dut, streams, n_out, fields_out, rates, ready_rate=0.7, seed=1):
    """Drive the sinks (name -> beats) with independent throttles; capture n_out beats."""
    prng = random.Random(seed)
    out  = []
    def driver(ep, beats, rate):
        def gen():
            for b in beats:
                for f, v in b.items():
                    yield getattr(ep, f).eq(int(v))
                yield ep.valid.eq(1)
                yield
                while not (yield ep.ready):
                    yield
                yield ep.valid.eq(0)
                while prng.random() > rate:
                    yield
        return gen()
    def capture():
        cycles = 0
        while len(out) < n_out:
            yield dut.source.ready.eq(int(prng.random() < ready_rate))
            yield
            cycles += 1
            assert cycles < 100000, "watchdog"
            if (yield dut.source.valid) and (yield dut.source.ready):
                beat = {}
                for f in fields_out:
                    beat[f] = (yield getattr(dut.source, f))
                out.append(beat)
    run_simulation(dut, [driver(getattr(dut, name), beats, rate) for (name, beats),
                         rate in zip(streams.items(), rates)] + [capture()])
    return out

class TestAlphaBlend(unittest.TestCase):
    # verify-tier: model — two 16 x 12 RGB streams with a constant alpha (independently throttled
    # sinks, watchdog) and a mono mask stream from a threshold-like image: bit-exact with the
    # framing from sink_a; alpha 0 / 256 identities; latency 1.
    def test_blend(self):
        a, b = images(2, 16, 12, 3, 1)
        for alpha in (128, 0, 256, 77):
            with self.subTest(alpha=alpha):
                dut = LiteDSPAlphaBlend(alpha=alpha, with_csr=False)
                out = simulate_join(
                    dut, {"sink_a": raster_beats(a, 3), "sink_b": raster_beats(b, 3)}, 192,
                    ["r", "g", "b", "eol", "first", "last"], rates=(0.8, 0.6))
                self.assertTrue(
                    np.array_equal(beats_to_image(out, 16, 12, 3), alpha_blend_model(a, b, alpha)))
                self.assertEqual([o["eol"] for o in out], [int(k % 16 == 15) for k in range(192)])
                self.assertEqual(dut.latency, 1)
        mask = np.where(images(1, 16, 12, 1, 2)[0] > 128, 255, 0)
        mask[0, :4] = 100
        dut = LiteDSPAlphaBlend(with_alpha_sink=True, with_csr=False)
        out = simulate_join(dut, {"sink_a": raster_beats(a, 3), "sink_b": raster_beats(b, 3),
                                  "sink_alpha": raster_beats(mask, 1)}, 192,
            ["r", "g", "b"], rates=(0.9, 0.7, 0.5))
        self.assertTrue(
            np.array_equal(beats_to_image(out, 16, 12, 3), alpha_blend_model(a, b, mask)))
        with self.assertRaises(ValueError):
            LiteDSPAlphaBlend(alpha=300, with_csr=False)

class TestBoxOverlay(unittest.TestCase):
    # verify-tier: model — three overlapping boxes (one partly outside) with thickness 2 on RGB
    # and mono 16 x 12 frames, loaded through the shadow table and committed: frame 0 untouched,
    # frame 1 drawn bit-exact; bypass; invalid parameters.
    def test_boxes(self):
        boxes = [(2, 1, 9, 6, (255, 0, 0), 1), (6, 4, 14, 10, (0, 255, 0), 1),
                 (12, 8, 20, 15, (0, 0, 255), 1), (0, 0, 3, 3, (9, 9, 9), 0)]
        for nc in (3, 1):
            with self.subTest(nc=nc):
                imgs = images(2, 16, 12, nc, seed=nc)
                bx   = [(x0, y0, x1, y1, c if nc == 3 else c[0], en)
                                                             for (x0, y0, x1, y1, c, en) in boxes]
                dut  = LiteDSPBoxOverlay(n_channels=nc, n_boxes=4, thickness=2, with_csr=False)
                def loader():
                    for k, (x0, y0, x1, y1, c, en) in enumerate(bx):
                        packed = sum(int(v) << (8*i) for i,
                                     v in enumerate(c)) if nc == 3 else int(c)
                        yield dut.box_index.eq(k); yield dut.box_x0.eq(x0); yield dut.box_y0.eq(
                            y0); yield dut.box_x1.eq(x1); yield dut.box_y1.eq(y1)
                        yield dut.box_color.eq(packed); yield dut.box_enable.eq(
                            en); yield dut.box_we.eq(1)
                        yield
                    yield dut.box_we.eq(0)
                    for _ in range(30):                                 # Commit inside frame 0.
                        yield
                    yield dut.commit.eq(1)
                    yield
                    yield dut.commit.eq(0)
                cap = run_frames(dut, imgs, 384, nc, sink_throttle=0.2, source_ready_rate=0.7,
                                 extra=[loader()])
                self.assertTrue(np.array_equal(beats_to_image(cap, 16, 12, nc), imgs[0]))
                self.assertTrue(np.array_equal(beats_to_image(cap[192:], 16, 12, nc),
                                               box_overlay_model(imgs[1], bx, 2)))
                self.assertEqual(dut.latency, 1)
        dut = LiteDSPBoxOverlay(with_csr=False)
        dut.bypass.reset = 1
        img = images(1, 16, 12, 3, 4)[0]
        self.assertTrue(
            np.array_equal(beats_to_image(run_frames(dut, [img], 192, 3), 16, 12, 3), img))
        for kwargs in ({"n_boxes": 0}, {"thickness": 16}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPBoxOverlay(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
