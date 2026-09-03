#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import random
import unittest

import numpy as np

from litedsp.radar.detect import LiteDSPPeakExtractor

from test.common import run_stream, column
from test.models import peak_extractor_model

FIELDS = ["range", "doppler", "data", "hit", "first", "last"]

def cells(data, detect, m):
    return [{"data": int(v), "detect": int(d), "threshold": 0, "first": int(k % m == 0), "last": int(k % m == m - 1)}
            for k, (v, d) in enumerate(zip(data, detect))]

class TestPeakExtractor(unittest.TestCase):
    def _check(self, cap, ref):
        for name, col in zip(FIELDS, ref):
            self.assertEqual(column(cap, name).tolist(), col.tolist(), name)

    # verify-tier: model — two CPIs of 16x8 random cells with a random detection map (about a
    # third of the cells), local-max on/off and interpolation on/off, bit-exact records and
    # terminators under backpressure.
    def test_bit_exact(self):
        prng = random.Random(6)
        N, M = 16, 8
        data   = [prng.randint(0, 5000) for _ in range(2*N*M)]
        detect = [int(prng.random() < 0.35) for _ in range(2*N*M)]
        for local_max, interpolate in ((1, 1), (0, 1), (1, 0)):
            with self.subTest(local_max=local_max, interpolate=interpolate):
                ref = peak_extractor_model(data, detect, N, M, local_max, interpolate)
                dut = LiteDSPPeakExtractor(n_range_bins=N, n_doppler_bins=M, with_csr=False)
                dut.local_max.reset, dut.interpolate.reset = local_max, interpolate
                cap = run_stream(dut, cells(data, detect, M), len(ref[0]), ["data", "detect", "first", "last"], FIELDS,
                    sink_throttle=0.2, source_ready_rate=0.7)
                self._check(cap, ref)
                self.assertIsNone(dut.latency)

    # verify-tier: bound — a Gaussian blob centred at (r0 + 0.3, c0 - 0.4) with all its cells
    # detected yields exactly one record within 0.1 bin of the true centroid; a flat 2x2 plateau
    # yields one record at its centre; an empty CPI is a single first & last terminator.
    def test_centroid_plateau_empty(self):
        N, M = 16, 8
        r0, c0 = 7.3, 3.6
        data   = [int(round(60000*math.exp(-((r - r0)**2 + (c - c0)**2)/(2*1.2**2)))) for r in range(N) for c in range(M)]
        detect = [int(v > 3000) for v in data]
        plateau = [0]*(N*M)
        for r, c in ((10, 4), (10, 5), (11, 4), (11, 5)):
            plateau[r*M + c] = 40000
        data2   = plateau
        detect2 = [int(v > 0) for v in plateau]
        empty   = [0]*(N*M)
        stream  = data + data2 + empty
        dets    = detect + detect2 + [0]*(N*M)
        ref = peak_extractor_model(stream, dets, N, M, 1, 1)
        dut = LiteDSPPeakExtractor(n_range_bins=N, n_doppler_bins=M, with_csr=False)
        cap = run_stream(dut, cells(stream, dets, M), len(ref[0]), ["data", "detect", "first", "last"], FIELDS,
            sink_throttle=0.0, source_ready_rate=1.0)
        self._check(cap, ref)
        hits = [b for b in cap if b["hit"]]
        self.assertEqual(len(hits), 2)
        self.assertLessEqual(abs(hits[0]["range"]/16 - r0), 0.1)
        self.assertLessEqual(abs(hits[0]["doppler"]/16 - c0), 0.1)
        # The 2x2 plateau yields one record (its raster-first cell) interpolated to the block's
        # centre (10.5, 4.5): the parabola clamps at +0.5 bin on both axes.
        self.assertEqual((hits[1]["range"], hits[1]["doppler"]), ((10 << 4) + 8, (4 << 4) + 8))
        terms = [b for b in cap if not b["hit"]]
        self.assertEqual([t["data"] for t in terms], [1, 1, 0])
        self.assertEqual((terms[2]["first"], terms[2]["last"]), (1, 1))

    def test_frame_error_and_invalid(self):
        N, M = 8, 8
        beats = cells([100]*(N*M), [0]*(N*M), M)
        beats[11]["first"] = 1
        dut = LiteDSPPeakExtractor(n_range_bins=N, n_doppler_bins=M, with_csr=False)
        run_stream(dut, beats, 1, ["data", "detect", "first", "last"], FIELDS, sink_throttle=0.0, source_ready_rate=1.0,
            extra=[self._read_error(dut)])
        self.assertEqual(self.error, 1)
        for kwargs in ({"n_range_bins": 1}, {"frac_bits": 0}, {"index_width": 3}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPPeakExtractor(with_csr=False, **kwargs)

    def _read_error(self, dut):
        from migen import passive
        @passive
        def gen():
            while True:
                self.error = (yield dut.frame_error)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
