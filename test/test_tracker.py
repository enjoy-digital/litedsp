#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.radar.track import LiteDSPAlphaBetaTracker

from test.common import run_stream, column
from test.models import alpha_beta_tracker_model, tracker_scenario

IN  = ["range", "doppler", "data", "hit", "first", "last"]
OUT = ["range", "doppler", "velocity", "id", "hits", "hit", "first", "last"]

def run(beats, **kwargs):
    ref, stats = alpha_beta_tracker_model([b["range"] for b in beats], [b["doppler"] for b in beats],
        [b["hit"] for b in beats], **kwargs)
    return ref, stats

class TestAlphaBetaTracker(unittest.TestCase):
    # verify-tier: model — 12 CPIs of two crossing targets, a false alarm per CPI and two dropped
    # detections: the track bursts (positions, velocities, ids, hit counts, framing) are
    # bit-exact against the integer model under backpressure, with and without tentative tracks.
    def test_bit_exact(self):
        beats, _ = tracker_scenario()
        for emit_tentative in (0, 1):
            with self.subTest(emit_tentative=emit_tentative):
                ref, stats = run(beats, emit_tentative=emit_tentative)
                dut = LiteDSPAlphaBetaTracker(with_csr=False)
                dut.emit_tentative.reset = emit_tentative
                cap = run_stream(dut, beats, len(ref[0]), IN, OUT, sink_throttle=0.2, source_ready_rate=0.6)
                for name, col in zip(OUT, ref):
                    got = column(cap, name, len(getattr(dut.source, name)) if name == "velocity" else None)
                    self.assertEqual(got.tolist(), col.tolist(), name)
                self.assertIsNone(dut.latency)

    # verify-tier: bound — on the same scenario both targets are confirmed at CPI 2 and tracked
    # through the crossing and the dropped detections with the same ids; once the velocity has
    # converged (~1/beta CPIs) the RMS position error over CPIs 8..11 is <= 0.3 bin and the
    # range-rate error <= 0.1 bin/CPI at the end; the false alarms never confirm.
    def test_tracking_quality(self):
        beats, truth = tracker_scenario()
        (rng, dop, vel, ids, hits, hit, first, last), _ = run(beats)
        bursts, cur = [], []
        for k in range(len(hit)):
            if hit[k]:
                cur.append((int(ids[k]), rng[k]/16, dop[k]/16, vel[k]/256))
            else:
                bursts.append(cur); cur = []
        self.assertEqual(len(bursts), 12)
        self.assertEqual(sorted(t[0] for t in bursts[2]), [0, 1])
        for c in range(2, 12):
            self.assertEqual(sorted(t[0] for t in bursts[c]), [0, 1], f"CPI {c}")
        err = []
        for c in range(8, 12):
            tr = {t[0]: t for t in bursts[c]}
            for (cc, k, r, d) in truth:
                if cc != c:
                    continue
                # Track id k follows target k: both were initialised in CPI 0 in record order.
                t = tr[k]
                err.append((t[1] - r)**2 + (t[2] - d)**2)
        self.assertLessEqual(np.sqrt(np.mean(err)), 0.3)
        tr = {t[0]: t for t in bursts[11]}
        self.assertLessEqual(abs(tr[0][3] - 0.5), 0.1)
        self.assertLessEqual(abs(tr[1][3] + 0.5), 0.1)

    # verify-tier: bound — coasting: a target missing for two CPIs keeps its track (max_misses 2),
    # one missing for three CPIs is freed and comes back under a new id.
    def test_coasting(self):
        beats, _ = tracker_scenario(n_cpi=14, drop=((4, 0), (5, 0), (7, 1), (8, 1), (9, 1)), false_alarms=False)
        (rng, dop, vel, ids, hits, hit, first, last), _ = run(beats)
        bursts, cur = [], []
        for k in range(len(hit)):
            if hit[k]:
                cur.append(int(ids[k]))
            else:
                bursts.append(sorted(cur)); cur = []
        self.assertEqual(bursts[4], [0, 1])                             # Coasting through two misses.
        self.assertEqual(bursts[5], [0, 1])
        self.assertEqual(bursts[6], [0, 1])                             # Re-assigned.
        self.assertEqual(bursts[8], [0, 1])                             # Two misses: still tracked.
        self.assertEqual(bursts[9], [0])                                # Third miss: freed.
        self.assertEqual(bursts[10], [0])                               # Re-acquired (tentative).
        self.assertEqual(bursts[12], [0, 1])                            # Re-confirmed after 3 hits.

    def test_invalid(self):
        for kwargs in ({"n_tracks": 17}, {"frac_bits": 9}, {"gain_frac": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPAlphaBetaTracker(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
