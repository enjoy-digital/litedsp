#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.radar.cfar_2d import LiteDSPCFAR2D
from litedsp.radar.design  import cfar_alpha

from test.common import run_stream, column
from test.models import cfar_2d_model

FIELDS = ["data", "threshold", "detect", "first", "last"]

def rows(values, m):
    return [{"data": int(v), "first": int(k % m == 0), "last": int(k % m == m - 1)} for k,
            v in enumerate(values)]

class TestCFAR2D(unittest.TestCase):
    def _check(self, cap, ref, n):
        for name, col in zip(FIELDS, ref):
            self.assertEqual(column(cap, name).tolist(), col[:n].tolist(), name)

    # verify-tier: model — two CPIs of 16x8 (box (2,1)/(1,1)) and of 8x16 (box (1,2)/(1,1), with a
    # threshold floor), exponential-like cells with a few strong targets, bit-exact (cell,
    # threshold,
    # decision, framing) under backpressure.
    def test_bit_exact(self):
        prng = random.Random(4)
        for N, M, n_train, floor in ((16, 8, (2, 1), 0), (8, 16, (1, 2), 5000)):
            with self.subTest(N=N, M=M, floor=floor):
                x = [min(int(prng.expovariate(1/3000)), 2**17 - 1) for _ in range(2*N*M)]
                for k in (0, N*M//2 + 3, 2*N*M - 1):
                    x[k] = 90000
                dut = LiteDSPCFAR2D(n_range_bins=N, n_doppler_bins=M, n_train=n_train,
                                    n_guard=(1, 1), with_csr=False)
                dut.threshold_min.reset = floor
                cap = run_stream(dut, rows(x, M), 2*N*M, ["data", "first", "last"], FIELDS,
                    sink_throttle=0.2, source_ready_rate=0.7)
                self._check(cap, cfar_2d_model(x, N, M, n_train, (1, 1), alpha=512,
                                               threshold_min=floor), 2*N*M)
                self.assertIsNone(dut.latency)

    # verify-tier: bound — a 64x16 exponential map with alpha for Pfa = 1e-3 over the 68-cell
    # training box: four injected targets (one two cells wide, surviving the guard) are all
    # detected with at most 5 false alarms in the interior (the zero-padded edges see smaller
    # training sums); the detection counter matches; bit-exact against the model.
    def test_map_detection(self):
        prng  = random.Random(0)
        N, M  = 64, 16
        x     = [min(int(prng.expovariate(1/1000)), 2**17 - 1) for _ in range(N*M)]
        targets = [(10, 3), (30, 12), (50, 7), (40, 9), (40, 10)]
        for r, c in targets:
            x[r*M + c] = 30000
        dut   = LiteDSPCFAR2D(with_csr=False)
        alpha = cfar_alpha(1e-3, dut.n_training, "power", frac_bits=8)
        dut.alpha.reset = alpha
        cap   = run_stream(dut, rows(x, M), N*M, ["data", "first", "last"], FIELDS,
                           sink_throttle=0.0,
            source_ready_rate=1.0, extra=[self._read_detections(dut)])
        detect = column(cap, "detect").reshape(N, M)
        for r, c in targets:
            self.assertEqual(detect[r, c], 1, (r, c))
        interior = detect[5:N - 5, 3:M - 3]                              # Zero padding lowers the
        false_alarms = int(interior.sum()) - 3                            # edge thresholds.
        self.assertLessEqual(false_alarms, 5)
        self.assertEqual(self.detections, int(detect.sum()))
        self._check(cap, cfar_2d_model(x, N, M, (4, 2), (1, 1), alpha=alpha), N*M)

    def test_frame_error_and_invalid(self):
        prng  = random.Random(2)
        x     = [prng.randint(0, 3000) for _ in range(2*16*8)]
        beats = rows(x, 8)
        beats[8*5 + 3]["first"] = 1
        dut   = LiteDSPCFAR2D(n_range_bins=16, n_doppler_bins=8, n_train=(2, 1), with_csr=False)
        run_stream(dut, beats, 4*8, ["data", "first", "last"], FIELDS, sink_throttle=0.0,
                   source_ready_rate=1.0,
            extra=[self._read_error(dut)])
        self.assertEqual(self.error, 1)
        for kwargs in ({"n_train": (0, 2)}, {"n_guard": (1, 5)}, {"n_doppler_bins": 4},
                       {"n_train": (4,)}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPCFAR2D(with_csr=False, **kwargs)

    def _read_detections(self, dut):
        from migen import passive
        @passive
        def gen():
            while True:
                self.detections = (yield dut.detections)
                yield
        return gen()

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
