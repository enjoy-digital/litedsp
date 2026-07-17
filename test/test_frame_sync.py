#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPFrameSync tests, bit-exact against ``frame_sync_model`` (CFAR preamble detector).

verify-tier: model
"""

import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.comm.frame_sync import LiteDSPFrameSync, frame_sync_taps

from test.common import run_stream, column
from test.models import frame_sync_model, fir_complex_model

BARKER7 = [1, 1, 1, -1, -1, 1, -1]

@passive
def _watch_detections(dut, stats):
    """Count `detected` pulses and mirror the running `count` register."""
    while True:
        if (yield dut.detected):
            stats["pulses"] += 1
        stats["count"] = (yield dut.count)
        yield

class TestFrameSync(unittest.TestCase):
    def run_frame_sync(self, sequence, xi, xq, threshold=None, frame_len=None, offset=0,
        peak_window=4, architecture="classic", **kwargs):
        dut = LiteDSPFrameSync(sequence, data_width=16, frame_len=frame_len,
            peak_window=peak_window, with_csr=False, architecture=architecture)
        if threshold is not None:
            dut.threshold.reset = threshold
        if offset:
            dut.offset.reset = offset
        stats = {"pulses": 0, "count": 0}
        n_out = len(xi) - dut.latency - 4  # The pipeline tail stays in flight at end of stream.
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))], n_out,
            ["i", "q"], ["i", "q", "first", "last"], extra=[_watch_detections(dut, stats)],
            **kwargs)
        return {
            "i":     column(cap, "i", 16),
            "q":     column(cap, "q", 16),
            "first": column(cap, "first"),
            "last":  column(cap, "last"),
            "stats": stats,
            "n_out": n_out,
        }

    def assert_matches_model(self, got, xi, xq, sequence, threshold, **model_kwargs):
        ri, rq, rf, rl, peaks = frame_sync_model(xi, xq, sequence, threshold, **model_kwargs)
        n = got["n_out"]
        np.testing.assert_array_equal(got["i"],     ri[:n], "payload I mismatch")
        np.testing.assert_array_equal(got["q"],     rq[:n], "payload Q mismatch")
        np.testing.assert_array_equal(got["first"], rf[:n], "`first` tag mismatch")
        np.testing.assert_array_equal(got["last"],  rl[:n], "`last` tag mismatch")
        self.assertEqual(got["stats"]["pulses"], len(peaks), "detected pulse count mismatch")
        self.assertEqual(got["stats"]["count"],  len(peaks), "count register mismatch")
        return peaks

    # verify-tier: model — two Barker-7 preambles embedded in noise: the whole output stream
    # (payload + first/last frame tags) and the detection count are bit-exact against
    # frame_sync_model, and `first`/`last` land exactly at preamble-end+1 / +frame_len.
    def test_detection_and_alignment_matches_model(self):
        rng = np.random.RandomState(3)
        xi  = rng.randint(-1500, 1500, 256)
        xq  = rng.randint(-1500, 1500, 256)
        for pos in (40, 120):
            xi[pos:pos + 7] = [4000*c for c in BARKER7]
            xq[pos:pos + 7] = 0
        thr = int(0.8*(1 << 14))  # Above the noise-only correlation ratios of this vector.
        got   = self.run_frame_sync(BARKER7, xi, xq, threshold=thr, frame_len=16)
        peaks = self.assert_matches_model(got, xi, xq, BARKER7, thr, frame_len=16)
        # Functional intent: peaks at the preamble ends, first right after, last 16 on.
        self.assertEqual(peaks, [46, 126])
        np.testing.assert_array_equal(np.flatnonzero(got["first"]), [47, 127])
        np.testing.assert_array_equal(np.flatnonzero(got["last"]),  [62, 142])

    # verify-tier: model — the CFAR compare is normalized by the window energy, so scaling
    # the input by x0.1 or x4 must yield the same detections at the same positions (each run
    # also stays bit-exact against the model at its own gain).
    def test_gain_invariance(self):
        rng  = np.random.RandomState(5)
        base = rng.randint(-500, 500, (2, 192))
        for pos in (30, 110):
            base[0, pos:pos + 7] = [1000*c for c in BARKER7]
            base[1, pos:pos + 7] = 0
        thr = int(0.8*(1 << 14))
        firsts = []
        for gain in (1.0, 0.1, 4.0):
            xi = (base[0]*gain).astype(np.int64)
            xq = (base[1]*gain).astype(np.int64)
            got = self.run_frame_sync(BARKER7, xi, xq, threshold=thr)
            self.assert_matches_model(got, xi, xq, BARKER7, thr)
            firsts.append(tuple(np.flatnonzero(got["first"])))
            self.assertEqual(got["stats"]["pulses"], 2, f"gain {gain}: missed detections")
        self.assertEqual(len(set(firsts)), 1, f"detections vary with input gain: {firsts}")

    # verify-tier: model — pure noise at a sane (0.9) normalized threshold: no detections,
    # no first/last tags, and still bit-exact against the model.
    def test_false_alarm_on_noise(self):
        rng = np.random.RandomState(7)
        xi  = rng.randint(-8000, 8000, 384)
        xq  = rng.randint(-8000, 8000, 384)
        thr = int(0.9*(1 << 14))
        got = self.run_frame_sync(BARKER7, xi, xq, threshold=thr)
        self.assert_matches_model(got, xi, xq, BARKER7, thr)
        self.assertEqual(got["stats"]["pulses"], 0, "false alarm on pure noise")
        self.assertEqual(got["first"].sum() + got["last"].sum(), 0)

    # verify-tier: model — the detection FSM advances only on accepted samples, so heavy
    # sink throttling + output backpressure must not move a single tag or payload bit.
    def test_backpressure_invariance(self):
        rng = np.random.RandomState(11)
        xi  = rng.randint(-1500, 1500, 160)
        xq  = rng.randint(-1500, 1500, 160)
        xi[60:67] = [4000*c for c in BARKER7]
        xq[60:67] = 0
        for architecture in ("classic", "pipelined"):
            free = self.run_frame_sync(BARKER7, xi, xq, frame_len=8,
                architecture=architecture, sink_throttle=0.0, source_ready_rate=1.0)
            stalled = self.run_frame_sync(BARKER7, xi, xq, frame_len=8,
                architecture=architecture, sink_throttle=0.4, source_ready_rate=0.5)
            classic_latency = LiteDSPFrameSync(BARKER7, with_csr=False).latency
            architecture_latency = LiteDSPFrameSync(BARKER7, with_csr=False,
                architecture=architecture).latency
            self.assertEqual(free["n_out"] + architecture_latency - classic_latency,
                len(xi) - classic_latency - 4)
            for field in ("i", "q", "first", "last"):
                np.testing.assert_array_equal(free[field], stalled[field],
                    f"{field} not handshake-invariant ({architecture})")
            self.assertEqual(free["stats"]["pulses"], stalled["stats"]["pulses"])

    def test_pipelined_architecture_matches_model(self):
        rng = np.random.RandomState(17)
        xi  = rng.randint(-1200, 1200, 192)
        xq  = rng.randint(-1200, 1200, 192)
        xi[70:77] = [3500*c for c in BARKER7]
        xq[70:77] = 0
        threshold = int(0.8*(1 << 14))
        got = self.run_frame_sync(BARKER7, xi, xq, threshold=threshold, frame_len=12,
            architecture="pipelined", sink_throttle=0.25, source_ready_rate=0.65)
        self.assert_matches_model(got, xi, xq, BARKER7, threshold, frame_len=12)

    # verify-tier: model — threshold boundary: with an isolated preamble, the exact edge
    # threshold (floor(|corr|^2 * 2^frac / (N * energy))) detects (>= is inclusive) and one
    # LSB above it does not; both sides bit-exact against the model.
    def test_threshold_boundary(self):
        amp = 2000
        xi  = np.zeros(96, np.int64)
        xq  = np.zeros(96, np.int64)
        xi[20:27] = [amp*c for c in BARKER7]
        # Peak-sample compare operands, straight from the datapath definition.
        coeffs_r, _ = frame_sync_taps(BARKER7)
        ci, _  = fir_complex_model(xi, xq, coeffs_r)
        energy = np.convolve(xi*xi + xq*xq, np.ones(7, np.int64))[:len(xi)]
        k      = 26  # Preamble end = correlation peak.
        edge   = int((int(ci[k])**2 << 14)//(7*int(energy[k])))
        for thr, expected in ((edge, 1), (edge + 1, 0)):
            got   = self.run_frame_sync(BARKER7, xi, xq, threshold=thr)
            peaks = self.assert_matches_model(got, xi, xq, BARKER7, thr)
            self.assertEqual(len(peaks), expected, f"threshold {thr}: expected {expected} detection(s)")

    # verify-tier: model — `offset` moves the `first` tag; peak_window=1 (tag the crossing
    # itself, no search) is the degenerate FSM path.
    def test_offset_and_peak_window(self):
        xi = np.zeros(80, np.int64)
        xq = np.zeros(80, np.int64)
        xi[20:27] = [3000*c for c in BARKER7]
        thr = 1 << 13
        got = self.run_frame_sync(BARKER7, xi, xq, offset=3)
        self.assert_matches_model(got, xi, xq, BARKER7, thr, offset=3)
        np.testing.assert_array_equal(np.flatnonzero(got["first"]), [30])  # 26 (peak) + 1 + 3.
        got = self.run_frame_sync(BARKER7, xi, xq, peak_window=1, frame_len=4)
        self.assert_matches_model(got, xi, xq, BARKER7, thr, peak_window=1, frame_len=4)

    # verify-tier: model — complex (QPSK-style) preamble exercises the two-FIR conjugate
    # recombine path, bit-exact against the model; (i, q) tuple form quantizes identically.
    def test_complex_sequence(self):
        seq = [1, 1j, -1, 1j, 1, -1j, -1, -1]
        self.assertEqual(frame_sync_taps(seq), frame_sync_taps([(c.real, c.imag) for c in seq]))
        rng = np.random.RandomState(9)
        xi  = rng.randint(-800, 800, 128)
        xq  = rng.randint(-800, 800, 128)
        amp = 3000
        xi[50:58] = [int(amp*c.real) for c in map(complex, seq)]
        xq[50:58] = [int(amp*c.imag) for c in map(complex, seq)]
        thr = int(0.8*(1 << 14))
        got   = self.run_frame_sync(seq, xi, xq, threshold=thr)
        peaks = self.assert_matches_model(got, xi, xq, seq, thr)
        self.assertEqual(peaks, [57])
        np.testing.assert_array_equal(np.flatnonzero(got["first"]), [58])

    # IRQ plumbing (squelch pattern): a detection latches ev.detected.pending.
    def test_irq_event(self):
        dut = LiteDSPFrameSync(BARKER7, with_csr=False, with_irq=True)
        samples = [(0, 0)]*8 + [(4000*c, 0) for c in BARKER7] + [(0, 0)]*24

        @passive
        def feed():
            yield dut.sink.valid.eq(1)
            for (i, q) in samples:
                yield dut.sink.i.eq(i)
                yield dut.sink.q.eq(q)
                yield
                while (yield dut.sink.ready) == 0:
                    yield
            yield dut.sink.valid.eq(0)
            while True:
                yield

        def check():
            yield dut.source.ready.eq(1)
            self.assertEqual((yield dut.ev.detected.pending), 0)
            for _ in range(200):
                if (yield dut.ev.detected.pending):
                    return
                yield
            self.fail("detection did not raise the event")

        run_simulation(dut, [feed(), check()])

if __name__ == "__main__":
    unittest.main()
