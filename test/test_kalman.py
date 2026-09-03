#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import unittest

import numpy as np

from litedsp.radar.kalman import LiteDSPKalmanTracker
from litedsp.radar.design import alpha_beta_from_index

from test.common import run_stream, column
from test.models import kalman_tracker_model, tracker_scenario

IN  = ["range", "doppler", "data", "hit", "first", "last"]
OUT = ["range", "doppler", "velocity", "id", "hits", "hit", "first", "last"]

def run(beats, **kwargs):
    return kalman_tracker_model([b["range"] for b in beats], [b["doppler"] for b in beats], [b["hit"] for b in beats], **kwargs)

class TestKalmanTracker(unittest.TestCase):
    # verify-tier: model — 12 CPIs of two crossing targets, a false alarm per CPI and two dropped
    # detections: the track bursts (Kalman-filtered positions, velocities, ids, hit counts,
    # framing) are bit-exact against the integer model under backpressure, with and without
    # tentative tracks.
    def test_bit_exact(self):
        beats, _ = tracker_scenario()
        for emit_tentative in (0, 1):
            with self.subTest(emit_tentative=emit_tentative):
                ref, stats = run(beats, emit_tentative=emit_tentative)
                dut = LiteDSPKalmanTracker(with_csr=False)
                dut.emit_tentative.reset = emit_tentative
                cap = run_stream(dut, beats, len(ref[0]), IN, OUT, sink_throttle=0.2, source_ready_rate=0.6,
                    extra=[self._read_sat(dut)])
                for name, col in zip(OUT, ref):
                    got = column(cap, name, len(getattr(dut.source, name)) if name == "velocity" else None)
                    self.assertEqual(got.tolist(), col.tolist(), name)
                self.assertEqual(self.cov_sat, stats["cov_sat"])
                self.assertEqual(self.cov_sat, 0)
                self.assertIsNone(dut.latency)

    # verify-tier: bound — a single constant-velocity target over 60 CPIs: the steady-state gains
    # are within 10 % of the Kalata alpha-beta values for the tracking index sqrt(q / r), for two
    # noise ratios; the position error settles below 0.2 bin.
    def test_steady_state_gains(self):
        for q, r in ((13, 128), (128, 128)):
            with self.subTest(q=q, r=r):
                beats = []
                for c in range(60):
                    rr, dd = 10.0 + 0.3*c, 4.0 + 0.1*c
                    beats.append({"range": int(round(rr*16)), "doppler": int(round(dd*16)), "data": 1000, "hit": 1, "first": 1, "last": 0})
                    beats.append({"range": 0, "doppler": 0, "data": 1, "hit": 0, "first": 0, "last": 1})
                (rng, dop, vel, ids, hits, hit, first, last), stats = run(beats, q=q, r=r, max_misses=15)
                a, b = alpha_beta_from_index(math.sqrt(q/r))
                k1, k2 = [g/256 for g in stats["gains"][0][0]]
                self.assertLessEqual(abs(k1 - a)/a, 0.10, (k1, a))
                self.assertLessEqual(abs(k2 - b)/b, 0.10, (k2, b))
                recs = [(rng[k]/16, vel[k]/256) for k in range(len(hit)) if hit[k]]
                self.assertLessEqual(abs(recs[-1][0] - (10.0 + 0.3*59)), 0.2)
                self.assertLessEqual(abs(recs[-1][1] - 0.3), 0.05)

    # verify-tier: bound — a target coasting for three CPIs with a huge process noise: the
    # predicted covariance clamps at the register width and the sticky cov_sat is set on the RTL
    # and the model (bit-exact through the clamps); invalid parameters.
    def test_covariance_saturation(self):
        beats, _ = tracker_scenario(n_cpi=7, drop=((2, 0), (3, 0), (4, 0)), false_alarms=False)
        ref, stats = run(beats, q=1 << 23, emit_tentative=1, max_misses=15)
        self.assertEqual(stats["cov_sat"], 1)
        dut = LiteDSPKalmanTracker(with_csr=False)
        dut.q.reset = 1 << 23
        dut.max_misses.reset = 15
        dut.emit_tentative.reset = 1
        cap = run_stream(dut, beats, len(ref[0]), IN, OUT, sink_throttle=0.0, source_ready_rate=1.0, extra=[self._read_sat(dut)])
        self.assertEqual(self.cov_sat, 1)
        for name, col in zip(OUT, ref):
            got = column(cap, name, len(getattr(dut.source, name)) if name == "velocity" else None)
            self.assertEqual(got.tolist(), col.tolist(), name)
        for kwargs in ({"cov_frac": 2}, {"cov_width": 8}, {"n_tracks": 17}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPKalmanTracker(with_csr=False, **kwargs)

    def _read_sat(self, dut):
        from migen import passive
        @passive
        def gen():
            while True:
                self.cov_sat = (yield dut.cov_sat)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
