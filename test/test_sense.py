#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.motor.sense import LiteDSPSigmaDeltaFilter, LiteDSPOvercurrentTrip

from test.common import run_stream, stream_driver, stream_capture, column
from test.models import (sigma_delta_filter_model, sigma_delta_stimulus, overcurrent_trip_model,
    bitstream_decimator_model)

FS = (1 << 15) - 1

def run_sense(dut, bits_channels, n_out, fields, throttle=0.2, ready_rate=0.7, extra=None):
    captured = []
    gens = [stream_driver(dut.sinks[k], [{"data": int(b)} for b in bits], ["data"],
                seed=10 + k, throttle=throttle) for k, bits in enumerate(bits_channels)]
    gens.append(stream_capture(dut.source, captured, n_out, fields, seed=20, ready_rate=ready_rate))
    run_simulation(dut, gens + (extra or []))
    return {f: column(captured, f, 16) for f in fields}

class TestSigmaDeltaFilter(unittest.TestCase):
    # verify-tier: model — three lock-stepped demodulators (independently throttled bit
    # sinks), bit-exact control-path output under backpressure.
    def test_bit_exact_main_path(self):
        R, n_out = 32, 40
        prng = random.Random(1)
        bits = [[prng.randint(0, 1) for _ in range(R*n_out)] for _ in range(3)]
        dut  = LiteDSPSigmaDeltaFilter(data_width=16, n_channels=3, decimation=R, n_stages=3,
            r_max=64, with_csr=False)
        got  = run_sense(dut, bits, n_out - 2, ["a", "b", "c"])
        refs, _ = sigma_delta_filter_model(bits, R, FS, r_max=64)
        for f, ref in zip(("a", "b", "c"), refs):
            self.assertTrue(np.array_equal(got[f], ref[:n_out - 2]), f)
        self.assertEqual(dut.latency, 1)

    # verify-tier: bound — a modulated current step from 0.2 to 0.9 pu on phase b trips the
    # fast path (sinc^3 over 16 bits) within a few fast windows, sets only phase b's sticky
    # flag and the IRQ, and clear releases it; phases a/c stay below the 0.6 pu threshold.
    def test_fast_path_trips(self):
        R, fast, n_bits = 64, 16, 64*24
        step = np.concatenate([np.full(n_bits//2, 0.2), np.full(n_bits - n_bits//2, 0.9)])
        bits = [sigma_delta_stimulus(np.full(n_bits, 0.2)), sigma_delta_stimulus(step),
                sigma_delta_stimulus(np.full(n_bits, -0.2))]
        dut = LiteDSPSigmaDeltaFilter(data_width=16, n_channels=3, decimation=R, n_stages=3,
            r_max=64, fast_decimation=fast, with_csr=False, with_irq=True)
        dut.threshold.reset = int(0.6*FS)
        log = []

        @passive
        def watch():
            while True:
                log.append(((yield dut.overcurrent), (yield dut.ev.overcurrent.pending)))
                yield

        run_sense(dut, bits, n_bits//R - 2, ["a", "b", "c"], throttle=0.0, ready_rate=1.0,
            extra=[watch()])
        flags = np.array([f for f, _ in log])
        first = int(np.argmax(flags != 0))
        self.assertEqual(int(flags[-1]), 0b010)                       # Only phase b.
        self.assertGreater(first, n_bits//2)                          # Not before the step.
        self.assertLess(first, n_bits//2 + 3*fast + 8)                # Within ~3 fast windows.
        self.assertEqual(log[-1][1], 1)                               # IRQ pending.
        _, trips = sigma_delta_filter_model(bits, R, int(0.6*FS), r_max=64, fast_decimation=fast)
        self.assertEqual(trips, [False, True, False])

    def test_clear_and_single_channel(self):
        R, n_out = 16, 20
        bits = [[1]*(R*n_out)]                                          # Full scale: trips.
        dut  = LiteDSPSigmaDeltaFilter(data_width=16, n_channels=1, decimation=R, n_stages=3,
            r_max=16, fast_decimation=8, with_csr=False)
        dut.threshold.reset = FS//2
        seen = []

        @passive
        def ctrl():
            for _ in range(200):
                yield
            seen.append((yield dut.overcurrent))
            yield dut.clear.eq(1)
            yield
            yield dut.clear.eq(0)
            yield
            seen.append((yield dut.overcurrent))
            while True:
                yield

        got = run_sense(dut, bits, n_out - 2, ["data"], throttle=0.0, ready_rate=1.0,
                        extra=[ctrl()])
        self.assertEqual(seen[0], 1)
        self.assertEqual(seen[1], 0)                                    # Cleared (re-trips later).
        self.assertTrue(np.all(got["data"][2:] == FS))                  # 100 % density = +FS.

    def test_invalid(self):
        for kwargs in ({"n_channels": 2}, {"fast_decimation": 1}, {"decimation": 1}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPSigmaDeltaFilter(with_csr=False, **kwargs)

class TestOvercurrentTrip(unittest.TestCase):
    # verify-tier: model — exact passthrough (latency 0) and the sticky trip sequence.
    def test_passthrough_and_trip(self):
        n    = 300
        prng = random.Random(4)
        a, b, c = ([prng.randint(-FS, FS) for _ in range(n)] for _ in range(3))
        thr  = 30000
        dut  = LiteDSPOvercurrentTrip(data_width=16, with_csr=False, with_irq=True)
        dut.threshold.reset = thr
        faults = []

        @passive
        def watch():
            while True:
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    yield
                    faults.append((yield dut.fault))
                else:
                    yield

        cap = run_stream(dut, [{"a": a[k], "b": b[k], "c": c[k]} for k in range(n)], n,
            ["a", "b", "c"], ["a", "b", "c"], sink_throttle=0.2, source_ready_rate=0.7,
            extra=[watch()])
        ra, rb, rc, rf = overcurrent_trip_model(a, b, c, thr)
        for f, r in (("a", ra), ("b", rb), ("c", rc)):
            self.assertTrue(np.array_equal(column(cap, f, 16), r), f)
        m = min(len(faults), n)                                      # Sim ends on the last capture.
        self.assertGreaterEqual(m, n - 1)
        self.assertTrue(np.array_equal(np.array(faults[:m]), rf.astype(int)[:m]))
        self.assertEqual(dut.latency, 0)

    def test_threshold_boundary_clear_count(self):
        dut = LiteDSPOvercurrentTrip(data_width=16, with_csr=False)
        dut.threshold.reset = 1000
        seq = [(1000, -1000, 0)]*10 + [(1001, 0, 0)] + [(0, 0, -1001)]*2 + [(0, 0, 0)]*80
        state = {}

        @passive
        def read():
            for _ in range(60):
                yield
            state["fault"], state["phase"], state["count"] = \
                (yield dut.fault), (yield dut.phase), (yield dut.count)
            yield dut.clear.eq(1)
            yield
            yield dut.clear.eq(0)
            yield
            state["after"] = (yield dut.fault), (yield dut.count)
            while True:
                yield

        run_stream(dut, [{"a": x, "b": y, "c": z} for x, y, z in seq], len(seq),
            ["a", "b", "c"], ["a", "b", "c"], sink_throttle=0.0, source_ready_rate=1.0,
            extra=[read()])
        self.assertEqual((state["fault"], state["phase"], state["count"]), (1, 0b101, 3))
        self.assertEqual(state["after"], (0, 0))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            LiteDSPOvercurrentTrip(data_width=2, with_csr=False)

if __name__ == "__main__":
    unittest.main()
