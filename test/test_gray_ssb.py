#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import random
import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.comm.gray    import LiteDSPGrayMapper, LiteDSPGrayDemapper
from litedsp.comm.ssb_mod import LiteDSPSSBModulator

from test.common import run_stream, column
from test.models import gray_model, ssb_modulator_model

class TestGray(unittest.TestCase):
    # verify-tier: model — exhaustive words for widths 1..6: adjacent codes (including the wrap)
    # differ in one bit, the demapper inverts the mapper, both bit-exact against the model under
    # backpressure on two-lane beats; latency 1.
    def test_gray(self):
        for width in range(1, 7):
            with self.subTest(width=width):
                n = 1 << width
                g = gray_model(range(n), width)
                self.assertTrue(all(bin(int(g[k]) ^ int(g[(k + 1) % n])).count("1") == 1 for k in range(n)))
                self.assertEqual(gray_model(g, width, encode=False).tolist(), list(range(n)))
                words = [(a << width) | b for a in range(n) for b in range(n)][:400]
                enc = LiteDSPGrayMapper(width=width, n_lanes=2, with_csr=False)
                cap = run_stream(enc, [{"data": w} for w in words], len(words), ["data"], ["data"], sink_throttle=0.2, source_ready_rate=0.7)
                self.assertEqual(column(cap, "data").tolist(), gray_model(words, width, 2).tolist())
                dec = LiteDSPGrayDemapper(width=width, n_lanes=2, with_csr=False)
                cap = run_stream(dec, [{"data": w} for w in column(cap, "data").tolist()], len(words), ["data"], ["data"], sink_throttle=0.2, source_ready_rate=0.7)
                self.assertEqual(column(cap, "data").tolist(), words)
                self.assertEqual(enc.latency, 1)
        with self.assertRaises(ValueError):
            LiteDSPGrayMapper(width=0, with_csr=False)

class TestSSB(unittest.TestCase):
    # verify-tier: model — 300 random samples, upper and lower sideband, bit-exact under
    # backpressure; opposite-sideband rejection >= 30 dB on tones at 0.1 .. 0.4 fs; invalid taps.
    def test_ssb(self):
        prng = random.Random(3)
        x = [prng.randint(-20000, 20000) for _ in range(300)]
        for sb in (0, 1):
            with self.subTest(sideband=sb):
                dut = LiteDSPSSBModulator(with_csr=False)
                dut.sideband.reset = sb
                cap = run_stream(dut, [{"data": v} for v in x], 300, ["data"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
                ri, rq = ssb_modulator_model(x, 31, sb)
                self.assertEqual(column(cap, "i", 16).tolist(), ri.tolist())
                self.assertEqual(column(cap, "q", 16).tolist(), rq.tolist())
        n = 512
        for f in (0.1, 0.25, 0.4):
            tone = [int(round(16000*math.cos(2*math.pi*f*k))) for k in range(n)]
            dut = LiteDSPSSBModulator(with_csr=False)
            cap = run_stream(dut, [{"data": v} for v in tone], n, ["data"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
            z = (column(cap, "i", 16) + 1j*column(cap, "q", 16))[64:]
            spec = np.abs(np.fft.fft(z*np.hanning(len(z))))
            freqs = np.fft.fftfreq(len(z))
            want = spec[np.argmin(np.abs(freqs - f))]
            image = spec[np.argmin(np.abs(freqs + f))]
            self.assertGreaterEqual(20*math.log10(want/max(image, 1e-9)), 30.0, f)
        with self.assertRaises(ValueError):
            LiteDSPSSBModulator(n_taps=8, with_csr=False)

if __name__ == "__main__":
    unittest.main()
