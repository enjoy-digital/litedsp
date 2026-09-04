#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.radar.cfar import LiteDSPCACFAR, LiteDSPOSCFAR

from test.common import run_stream, column
from test.models import os_cfar_model, ca_cfar_model

FIELDS = ["data", "threshold", "detect", "first", "last"]

def frames(values, n):
    return [{"data": int(v), "first": int(k % n == 0), "last": int(k % n == n - 1)} for k,
            v in enumerate(values)]

class TestOSCFAR(unittest.TestCase):
    # verify-tier: model — two 64-cell frames, ranks 0 (minimum), 5 (default 3/4 quantile) and 7
    # (maximum) with ties in the data, bit-exact (cell, threshold, decision, framing) under
    # backpressure.
    def test_bit_exact(self):
        prng  = random.Random(8)
        x     = [min(int(prng.expovariate(1/3000)), 2**17 - 1)//64*64 for _ in range(2*64)]  # Ties.
        beats = frames(x, 64)
        first = [b["first"] for b in beats]; last = [b["last"] for b in beats]
        for rank in (0, 5, 7):
            with self.subTest(rank=rank):
                dut = LiteDSPOSCFAR(n_train=4, n_guard=2, with_csr=False)
                dut.rank.reset = rank
                cap = run_stream(dut, beats, 2*64, ["data", "first", "last"], FIELDS,
                                 sink_throttle=0.2, source_ready_rate=0.7)
                ref = os_cfar_model(x, first, last, 4, 2, rank=rank, alpha=1024)
                for name, col in zip(FIELDS, ref):
                    self.assertEqual(column(cap, name).tolist(), col.tolist(), name)
                self.assertIsNone(dut.latency)

    # verify-tier: bound — interferer masking: two targets three cells apart (inside each other's
    # training window) over a flat background; the CA mean is captured by the neighbour and
    # misses the weaker target, the ordered statistic detects both.
    def test_interferer_masking(self):
        x = [1000]*64
        x[30], x[33] = 60000, 12000
        beats = frames(x, 64)
        first = [b["first"] for b in beats]; last = [b["last"] for b in beats]
        os_ = LiteDSPOSCFAR(n_train=4, n_guard=1, with_csr=False)
        os_.alpha.reset = 4 << 8                                        # 4x the ranked cell.
        cap = run_stream(os_, beats, 64, ["data", "first", "last"], FIELDS, sink_throttle=0.0,
                         source_ready_rate=1.0)
        self.assertEqual(sorted(np.flatnonzero(column(cap, "detect")).tolist()), [30, 33])
        ca = LiteDSPCACFAR(n_train=4, n_guard=1, with_csr=False)
        ca.alpha.reset = 4 << 8                                         # 4x the mean.
        cap = run_stream(ca, beats, 64, ["data", "first", "last"], FIELDS, sink_throttle=0.0,
                         source_ready_rate=1.0)
        self.assertEqual(sorted(np.flatnonzero(column(cap, "detect")).tolist()), [30])
        self.assertEqual(column(cap, "detect").tolist(),
                         list(ca_cfar_model(x, first, last, 4, 1, alpha=4 << 8)[2]))

    def test_invalid(self):
        for kwargs in ({"n_train": 9}, {"rank": 8}, {"rank": -1}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPOSCFAR(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
