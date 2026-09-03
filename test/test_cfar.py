#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.common       import real_layout
from litedsp.radar.cfar   import LiteDSPCACFAR
from litedsp.radar.design import cfar_alpha
from litedsp.stream.split import LiteDSPSplit

from test.common import run_stream, column
from test.models import ca_cfar_model

FIELDS = ["data", "threshold", "detect", "first", "last"]

def frames(values, n):
    return [{"data": int(v), "first": int(k % n == 0), "last": int(k % n == n - 1)} for k, v in enumerate(values)]

class _SplitFronted(Module):
    """Split -> CA-CFAR with the other branch always ready (guards the sink.ready rule)."""
    def __init__(self, cfar):
        self.submodules.split = split = LiteDSPSplit(2, layout=real_layout(cfar.data_width))
        self.submodules.cfar  = cfar
        self.sink, self.source = split.sink, cfar.source
        self.comb += [split.sources[0].connect(cfar.sink), split.sources[1].ready.eq(1)]

class TestCACFAR(unittest.TestCase):
    def _check(self, cap, ref, n):
        for name, col in zip(FIELDS, ref):
            self.assertEqual(column(cap, name).tolist(), col[:n].tolist(), name)

    # verify-tier: model — two 64-cell frames of exponential-like cells, CA / GO / SO statistics,
    # bit-exact (cell, threshold, decision, framing) under backpressure.
    def test_bit_exact(self):
        prng  = random.Random(3)
        x     = [min(int(prng.expovariate(1/3000)), 2**17 - 1) for _ in range(2*64)]
        beats = frames(x, 64)
        first = [b["first"] for b in beats]; last = [b["last"] for b in beats]
        for mode in (0, 1, 2):
            with self.subTest(mode=mode):
                dut = LiteDSPCACFAR(n_train=8, n_guard=2, with_csr=False)
                dut.mode.reset = mode
                cap = run_stream(dut, beats, 2*64, ["data", "first", "last"], FIELDS,
                    sink_throttle=0.2, source_ready_rate=0.7)
                self._check(cap, ca_cfar_model(x, first, last, 8, 2, alpha=512, mode=mode), 2*64)
                self.assertIsNone(dut.latency)

    # verify-tier: bound — 4096 exponential cells (power domain) with alpha from cfar_alpha for
    # Pfa = 1e-2 give a measured false-alarm rate within 0.3..3x of the design value; the CSR
    # detection counter matches.
    def test_false_alarm_rate(self):
        prng  = random.Random(0)
        n     = 4096
        x     = [min(int(prng.expovariate(1/1000)), 2**17 - 1) for _ in range(n)]
        alpha = cfar_alpha(1e-2, 16, "power", frac_bits=8)
        dut   = LiteDSPCACFAR(n_train=8, n_guard=2, with_csr=False)
        dut.alpha.reset = alpha
        beats = frames(x, n)
        cap   = run_stream(dut, beats, n, ["data", "first", "last"], FIELDS, sink_throttle=0.0,
            source_ready_rate=1.0, extra=[self._read_detections(dut)])
        det = int(column(cap, "detect").sum())
        self.assertGreaterEqual(det, int(0.3*1e-2*n))
        self.assertLessEqual(det, int(3*1e-2*n))
        self.assertEqual(self.detections, det)

    # verify-tier: bound — targets on the first and last cells of a frame (one-sided training
    # windows) and one in the middle are detected; a Split-fronted run does not deadlock.
    def test_edge_targets_and_split(self):
        prng = random.Random(5)
        x    = [prng.randint(500, 1500) for _ in range(64)]
        for pos in (0, 31, 63):
            x[pos] = 60000
        beats = frames(x, 64)
        first = [b["first"] for b in beats]; last = [b["last"] for b in beats]
        alpha = cfar_alpha(1e-3, 16, "power", frac_bits=8)      # ~8.7: the one-sided edge windows
        dut   = LiteDSPCACFAR(n_train=8, n_guard=2, with_csr=False)  # see half the training sum.
        dut.alpha.reset = alpha
        top   = _SplitFronted(dut)
        cap   = run_stream(top, beats, 64, ["data", "first", "last"], FIELDS, sink_throttle=0.3, source_ready_rate=0.6)
        self._check(cap, ca_cfar_model(x, first, last, 8, 2, alpha=alpha, mode=0), 64)
        detect = column(cap, "detect")
        self.assertEqual(sorted(np.flatnonzero(detect).tolist()), [0, 31, 63])

    def test_invalid(self):
        for kwargs in ({"n_train": 0}, {"n_train": 33}, {"n_guard": 9}, {"threshold_frac": 16}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPCACFAR(with_csr=False, **kwargs)

    def _read_detections(self, dut):
        from migen import passive
        @passive
        def gen():
            while True:
                self.detections = (yield dut.detections)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
