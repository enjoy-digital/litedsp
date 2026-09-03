#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.image.video import LiteDSPPixelFromVideo, LiteDSPPixelToVideo

from test.common import run_stream, raster_beats, beats_to_image, column
from test.models import video_frames, pixel_from_video_model

VIDEO = ["hsync", "vsync", "de", "r", "g", "b"]
PIX   = ["r", "g", "b", "eol", "first", "last"]

def images(n, w=16, h=12, seed=1):
    prng = random.Random(seed)
    return [np.array([[[prng.randint(0, 255) for _ in range(3)] for _ in range(w)] for _ in range(h)]) for _ in range(n)]

class TestPixelFromVideo(unittest.TestCase):
    # verify-tier: model — two 16 x 12 frames with blanking under backpressure: the active pixels
    # come out framed and bit-exact, blanking never stalls the timing source; pinned latency 1.
    def test_frames(self):
        imgs  = images(2)
        beats = video_frames(imgs)
        dut   = LiteDSPPixelFromVideo(width=16, height=12, with_csr=False)
        cap   = run_stream(dut, beats, 2*16*12, VIDEO, PIX, sink_throttle=0.2, source_ready_rate=0.7)
        ref   = pixel_from_video_model(beats, 16, 12)
        for name, col in zip(PIX, ref):
            self.assertEqual(column(cap, name).tolist(), col.tolist(), name)
        for k in range(2):
            self.assertTrue(np.array_equal(beats_to_image(cap[k*192:], 16, 12, 3), imgs[k]))
        self.assertEqual(dut.latency, 1)

    # verify-tier: bound — a short line (14 pixels) and a long line (18) set the sticky geometry
    # error; the frame counter counts.
    def test_geometry_error(self):
        imgs  = images(1)
        beats = video_frames(imgs)
        for k, b in enumerate(beats):
            if b["vcount"] == 3 and b["hcount"] >= 14:
                b["de"] = 0                                             # Short line 3.
        dut = LiteDSPPixelFromVideo(width=16, height=12, with_csr=False)
        run_stream(dut, beats, 16*12 - 2, VIDEO, PIX, sink_throttle=0.0, source_ready_rate=1.0,
            extra=[self._status(dut, len(beats) + 20)])                # Active: runs the trailing blanking.
        self.assertEqual(self.err, 1)
        self.assertEqual(self.frames, 1)
        with self.assertRaises(ValueError):
            LiteDSPPixelFromVideo(width=1, with_csr=False)

    def _status(self, dut, cycles):
        def gen():
            for _ in range(cycles):
                self.err = (yield dut.geometry_error)
                self.frames = (yield dut.frames)
                yield
        return gen()

class TestPixelToVideo(unittest.TestCase):
    # verify-tier: model — a timing generator stream and framed pixels: the video output carries
    # the pixels on the active beats and black elsewhere, bit-exact for two frames under pixel
    # backpressure; a throttled line underflows (black + sticky flag) and the next frame recovers.
    def test_frames_and_underflow(self):
        imgs   = images(2)
        timing = video_frames(imgs)                                     # hcount / vcount / de / syncs.
        pixels = raster_beats(imgs[0], 3) + raster_beats(imgs[1], 3)
        dut    = LiteDSPPixelToVideo(with_csr=False)
        out    = self._run(dut, timing, pixels, len(timing), pixel_rate=1.0)
        expect = [(b["de"], b["r"], b["g"], b["b"]) for b in timing]
        self.assertEqual([(o["de"], o["r"], o["g"], o["b"]) for o in out], expect)
        self.assertEqual([o["vsync"] for o in out], [b["vsync"] for b in timing])
        self.assertEqual(self.underflow, 0)
        # Starve the pixels during frame 0 line 5: those active beats are black and flagged; frame 1
        # (after the re-sync on its first pixel) is intact.
        dut = LiteDSPPixelToVideo(with_csr=False)
        out = self._run(dut, timing, pixels, len(timing), pixel_rate=1.0, starve=(5, 16))
        self.assertEqual(self.underflow, 1)
        self.assertGreaterEqual(self.underflows, 1)
        n0 = (16 + 6)*3 + (16 + 6)*(12 + 3)                            # Leading blanking + frame 0.
        f1 = [(o["de"], o["r"], o["g"], o["b"]) for o in out[n0:]]
        self.assertEqual(f1, expect[n0:])
        self.assertEqual(dut.latency, 1)

    def _run(self, dut, timing, pixels, n_out, pixel_rate=1.0, starve=None):
        prng = random.Random(3)
        out  = []
        def vtg():
            for b in timing:
                for f in ("hsync", "vsync", "de", "hres", "vres", "hcount", "vcount"):
                    yield getattr(dut.vtg_sink, f).eq(b[f])
                yield dut.vtg_sink.valid.eq(1)
                yield
                while not (yield dut.vtg_sink.ready):
                    yield
            yield dut.vtg_sink.valid.eq(0)
            for _ in range(4):
                yield
            self.underflow  = (yield dut.underflow)
            self.underflows = (yield dut.underflows)
        def pix():
            k = 0
            for b in pixels:
                if starve and k == starve[0]*16 and b["first"] == 0:
                    for _ in range(starve[1]*3):                         # Miss a whole line's worth.
                        yield
                for f in ("r", "g", "b", "eol", "first", "last"):
                    yield getattr(dut.sink, f).eq(b[f])
                yield dut.sink.valid.eq(1)
                yield
                while not (yield dut.sink.ready):
                    yield
                yield dut.sink.valid.eq(0)
                while prng.random() > pixel_rate:
                    yield
                k += 1
        @passive
        def capture():
            yield dut.source.ready.eq(1)
            while True:
                if (yield dut.source.valid):
                    beat = {}
                    for f in ("hsync", "vsync", "de", "r", "g", "b"):
                        beat[f] = (yield getattr(dut.source, f))
                    out.append(beat)
                yield
        run_simulation(dut, [vtg(), pix(), capture()])
        return out

if __name__ == "__main__":
    unittest.main()
