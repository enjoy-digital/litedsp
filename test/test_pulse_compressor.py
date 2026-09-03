#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.radar.compress import LiteDSPPulseCompressor
from litedsp.radar.waveform import chirp_reference

from test.common import run_stream, column
from test.models import pulse_compressor_model

def scene(prng, n, P, bandwidth, echoes, noise=300):
    """Noise plus attenuated chirp echoes at the given (delay, amplitude) pairs, framed as one pulse."""
    s = chirp_reference(P, bandwidth)
    x = np.array([complex(prng.randint(-noise, noise), prng.randint(-noise, noise)) for _ in range(n)])
    for d, a in echoes:
        x[d:d + P] += a*s
    return [{"i": int(np.clip(v.real, -32767, 32767)), "q": int(np.clip(v.imag, -32767, 32767)),
             "first": int(k == 0), "last": int(k == n - 1)} for k, v in enumerate(x)]

class TestPulseCompressor(unittest.TestCase):
    # verify-tier: model — bit-exact against the two-FIR model with the framing tags re-aligned
    # by pulse_len - 1, under backpressure, for the rectangular and Hamming references.
    def test_bit_exact(self):
        prng = random.Random(1)
        for window, P in (("rect", 16), ("hamming", 16)):
            with self.subTest(window=window):
                beats = scene(prng, 300, P, 0.5, [(40, 0.6), (120, 0.3)])
                dut = LiteDSPPulseCompressor(pulse_len=P, bandwidth=0.5, window=window, with_csr=False)
                cap = run_stream(dut, beats, 296, ["i", "q", "first", "last"], ["i", "q", "first", "last"],
                    sink_throttle=0.2, source_ready_rate=0.7)
                ri, rq, rf, rl = pulse_compressor_model([b["i"] for b in beats], [b["q"] for b in beats],
                    [b["first"] for b in beats], [b["last"] for b in beats], P, 0.5, window=window)
                self.assertTrue(np.array_equal(column(cap, "i", 16), ri[:296]))
                self.assertTrue(np.array_equal(column(cap, "q", 16), rq[:296]))
                self.assertEqual(column(cap, "first").tolist(), rf[:296].tolist())
                self.assertEqual(column(cap, "last").tolist(), rl[:296].tolist())
                self.assertEqual(dut.latency, dut.fir_re.latency + 1)

    # verify-tier: bound — an echo at delay d peaks at output position d + P - 1 (the tag
    # re-alignment puts range bin d at position d of the compressed frame); peak-to-sidelobe
    # ratio outside the main lobe (+/- 2 samples rect, +/- 4 Hamming) >= 10 dB for the
    # rectangular P=16 reference (measured 13 dB) and >= 15 dB for Hamming P=32 (measured
    # 17 dB; the time-bandwidth product of 16 bounds the taper's benefit).
    def test_peaks_and_sidelobes(self):
        for window, P, pslr, lobe in (("rect", 16, 10.0, 2), ("hamming", 32, 15.0, 4)):
            with self.subTest(window=window):
                prng  = random.Random(3)
                beats = scene(prng, 200, P, 0.5, [(60, 0.8)], noise=0)
                dut   = LiteDSPPulseCompressor(pulse_len=P, bandwidth=0.5, window=window, with_csr=False)
                cap   = run_stream(dut, beats, 196, ["i", "q", "first", "last"], ["i", "q", "first", "last"],
                    sink_throttle=0.0, source_ready_rate=1.0)
                mag   = np.hypot(column(cap, "i", 16), column(cap, "q", 16))
                peak  = int(np.argmax(mag))
                self.assertEqual(peak, 60 + P - 1)
                side  = np.max(np.concatenate([mag[:peak - lobe], mag[peak + lobe + 1:]]))
                self.assertGreaterEqual(20*np.log10(mag[peak]/max(side, 1)), pslr)
                self.assertEqual(column(cap, "first").tolist().index(1), P - 1)   # Re-aligned tag.

    def test_invalid(self):
        for kwargs in ({"pulse_len": 1}, {"bandwidth": 1.5}, {"window": "kaiser"}, {"shift": -1}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPPulseCompressor(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
