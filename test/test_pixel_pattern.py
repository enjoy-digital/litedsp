#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.image.pattern import LiteDSPPixelPattern, PATTERNS

from test.common import run_stream, beats_to_image
from test.models import pixel_pattern_model

class TestPixelPattern(unittest.TestCase):
    # verify-tier: model — every mode at 16 x 12 (RGB, and the mono Bayer mosaic) under a throttled
    # source: two frames bit-exact with the framing tags; the 20-wide case exercises the bar
    # remainder.
    def test_modes(self):
        for mode in PATTERNS:
            nc = 1 if mode == "bayer" else 3
            w  = 20 if mode == "bars" else 16
            with self.subTest(mode=mode):
                dut = LiteDSPPixelPattern(n_channels=nc, width=w, height=12, mode=mode, with_csr=False)
                dut.enable.reset = 1
                fields = (["data"] if nc == 1 else ["r", "g", "b"]) + ["eol", "first", "last"]
                cap = run_stream(dut, None, 2*w*12, [], fields, source_ready_rate=0.7)
                ref = pixel_pattern_model(mode, w, 12, 8, nc)
                for k in range(2):
                    self.assertTrue(np.array_equal(beats_to_image(cap[k*w*12:], w, 12, nc), ref), f"frame {k}")
                self.assertEqual([b["first"] for b in cap], [int(k % (w*12) == 0) for k in range(2*w*12)])
                self.assertEqual([b["eol"] for b in cap], [int(k % w == w - 1) for k in range(2*w*12)])
                self.assertEqual([b["last"] for b in cap], [int(k % (w*12) == w*12 - 1) for k in range(2*w*12)])

    # verify-tier: bound — trigger sends exactly one frame then the source idles; the frame
    # counter and busy flag follow; invalid geometry.
    def test_trigger(self):
        dut = LiteDSPPixelPattern(n_channels=1, width=16, height=4, mode="counter", with_csr=False)
        cap = run_stream(dut, None, 16*4, [], ["data", "last"], source_ready_rate=1.0, extra=[self._pulse(dut)])
        self.assertEqual(cap[-1]["last"], 1)
        self.assertEqual(self.frames, 1)
        self.assertEqual(self.extra_beats, 0)
        with self.assertRaises(ValueError):
            LiteDSPPixelPattern(width=4, with_csr=False)

    def _pulse(self, dut):
        def gen():                                                      # Active: keeps the simulation
            yield dut.trigger.eq(1)                                     # running after the capture.
            yield
            yield dut.trigger.eq(0)
            beats = 0
            for _ in range(200):
                if (yield dut.source.valid) and (yield dut.source.ready):
                    beats += 1
                yield
            self.frames = (yield dut.frames)
            self.extra_beats = beats - 64
        return gen()

if __name__ == "__main__":
    unittest.main()
