#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.radar.clutter import LiteDSPClutterMap

from test.common import run_stream, column
from test.models import clutter_map_model

FIELDS = ["data", "threshold", "detect", "first", "last"]

def scans(values, n):
    return [{"data": int(v), "first": int(k % n == 0), "last": int(k % n == n - 1)} for k, v in enumerate(values)]

class TestClutterMap(unittest.TestCase):
    # verify-tier: model — three 64-cell scans of exponential-like cells with a few strong
    # returns, censored and learn-all updates, bit-exact (cell, threshold, decision, framing)
    # under backpressure; pinned latency 4.
    def test_bit_exact(self):
        prng  = random.Random(10)
        x     = [min(int(prng.expovariate(1/3000)), 2**17 - 1) for _ in range(3*64)]
        for k in (70, 71, 140):
            x[k] = 100000
        beats = scans(x, 64)
        first = [b["first"] for b in beats]; last = [b["last"] for b in beats]
        for learn_all in (0, 1):
            with self.subTest(learn_all=learn_all):
                dut = LiteDSPClutterMap(n_range_bins=64, with_csr=False)
                dut.learn_all.reset = learn_all
                cap = run_stream(dut, beats, 3*64, ["data", "first", "last"], FIELDS, sink_throttle=0.2, source_ready_rate=0.7)
                ref = clutter_map_model(x, first, last, 64, alpha=1024, learn_all=learn_all)
                for name, col in zip(FIELDS, ref):
                    self.assertEqual(column(cap, name).tolist(), col.tolist(), name)
                self.assertEqual(dut.latency, 4)

    # verify-tier: bound — stationary clutter (a fixed profile + 10 % noise) produces no detection
    # once the map has converged (scans 8..11), a new return 6x above its cell's clutter detects
    # on scan 12, and after 'freeze' the map stops learning it (it keeps detecting).
    def test_convergence_and_freeze(self):
        prng    = random.Random(3)
        profile = [1000 + 200*(k % 7) + 3000*(k in (10, 40)) for k in range(64)]
        x = []
        for s in range(16):
            x += [int(p*(1 + prng.uniform(-0.1, 0.1))) for p in profile]
        for s in range(12, 16):
            x[s*64 + 25] = 6*profile[25]
        beats = scans(x, 64)
        dut = LiteDSPClutterMap(n_range_bins=64, with_csr=False)
        dut.alpha.reset = int(round(2.5*256))
        cap = run_stream(dut, beats, 16*64, ["data", "first", "last"], FIELDS, sink_throttle=0.0, source_ready_rate=1.0,
            extra=[self._freeze_at(dut, beats, 13*64)])
        det = column(cap, "detect").reshape(16, 64)
        self.assertEqual(int(det[8:12].sum()), 0)
        self.assertEqual(det[12, 25], 1)
        self.assertEqual(int(det[12:16, 25].sum()), 4)                    # Censored: never learned.
        self.assertEqual(int(det[8:16].sum()), 4)
        with self.assertRaises(ValueError):
            LiteDSPClutterMap(n_range_bins=4, n_doppler_bins=1, with_csr=False)

    def _freeze_at(self, dut, beats, n):
        from migen import passive
        @passive
        def gen():
            count = 0
            while True:
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    count += 1
                    if count == n:
                        yield dut.freeze.eq(1)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
