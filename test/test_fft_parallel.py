#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the parallel FFT (litedsp/analysis/fft_parallel.py).

The acceptance criterion is bit-identity with the serial scaled-mode FFT on the flattened
lane stream: the same input sequence delivered two samples per beat must produce the same
N outputs (bit-reversed order, same 1/N scaling) as :class:`LiteDSPFFT` one per beat — the
reference is both the pinned :func:`parallel_fft_model` / :func:`fft_fixed_model` and a
direct co-simulation of the serial gateware. Throughput (a sustained 2 samples/cycle under
free flow) and the declared latency are pinned cycle-exact.
"""

import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.analysis.fft          import LiteDSPFFT
from litedsp.analysis.fft_parallel import (
    LiteDSPParallelFFT,
    _LiteDSPFFTVectorStage,
    _LiteDSPFFTVectorPipelinedStage,
)

from test.common import run_stream, column, to_signed
from test.models import fft_fixed_model, parallel_fft_model

# Helpers ------------------------------------------------------------------------------------------

def pack_lanes(values, data_width=16):
    """Pack per-lane integers into one multi-sample field (lane 0 in the LSBs)."""
    mask = (1 << data_width) - 1
    word = 0
    for k, v in enumerate(values):
        word |= (int(v) & mask) << (k*data_width)
    return word

def flatten(captured, field, n_samples=2, data_width=16):
    """Flattened lane stream of one field (lane 0 = first sample of each beat)."""
    out = []
    for c in captured:
        word = c[field]
        out += list(to_signed([(word >> (k*data_width)) & ((1 << data_width) - 1)
                               for k in range(n_samples)], data_width))
    return np.array(out)

# Bit-Identity -------------------------------------------------------------------------------------

class TestParallelFFTBitExact(unittest.TestCase):
    def run_parallel(self, xi, xq, N, n_frames, throttle=0.0, ready=1.0,
        core_architecture="classic"):
        """Feed 2 samples/beat, capture ``n_frames`` output frames (i/q + framing markers).

        As with the serial SDF FFT, the pipeline holds about one frame (frame f streams out
        while frame f+1 streams in), so ``n_frames`` must leave the last input frame in
        flight (callers pass one frame more than they capture).
        """
        dut   = LiteDSPParallelFFT(N=N, core_architecture=core_architecture, with_csr=False)
        beats = [{"i": pack_lanes(xi[k:k + 2]), "q": pack_lanes(xq[k:k + 2])}
                 for k in range(0, len(xi), 2)]
        return run_stream(dut, beats, n_frames*N//2, ["i", "q"],
            ["i", "q", "first", "last"], sink_throttle=throttle, source_ready_rate=ready)

    def check_bit_identical(self, N, throttle=0.0, ready=1.0, nfr=4,
        core_architecture="classic"):
        rng = np.random.RandomState(N)
        xi  = rng.randint(-25000, 25000, nfr*N)
        xq  = rng.randint(-25000, 25000, nfr*N)
        cap = self.run_parallel(xi, xq, N, nfr - 1, throttle=throttle, ready=ready,
            core_architecture=core_architecture)
        gi  = flatten(cap, "i")
        gq  = flatten(cap, "q")
        # Serial gateware co-simulation on the same sample sequence (flattened lanes): the
        # serial capture's first frame starts at beat N-1 (delay-feedback fill, cf. test_fft).
        sdut    = LiteDSPFFT(N=N, with_csr=False)
        samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))]
        scap    = run_stream(sdut, samples, len(xi) - 1, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        si, sq  = column(scap, "i", 16), column(scap, "q", 16)
        for f in range(nfr - 1):
            s = (N - 1) + f*N
            np.testing.assert_array_equal(gi[f*N:(f + 1)*N], si[s:s + N],
                f"N={N} frame {f}: parallel != serial gateware (I)")
            np.testing.assert_array_equal(gq[f*N:(f + 1)*N], sq[s:s + N],
                f"N={N} frame {f}: parallel != serial gateware (Q)")
            # And against the pinned models (parallel_fft_model is fft_fixed_model re-laned).
            ri, rq = fft_fixed_model(xi[f*N:(f + 1)*N], xq[f*N:(f + 1)*N])
            np.testing.assert_array_equal(gi[f*N:(f + 1)*N], ri, f"N={N} frame {f} I")
            np.testing.assert_array_equal(gq[f*N:(f + 1)*N], rq, f"N={N} frame {f} Q")
            pi, pq = parallel_fft_model(xi[f*N:(f + 1)*N], xq[f*N:(f + 1)*N])
            np.testing.assert_array_equal(gi[f*N:(f + 1)*N], pi.reshape(-1))
            np.testing.assert_array_equal(gq[f*N:(f + 1)*N], pq.reshape(-1))
        # Framing: first/last on beats 0 / N/2-1 of every output frame.
        nb = N//2
        for k, c in enumerate(cap):
            self.assertEqual(c["first"], 1 if k % nb == 0 else 0,       f"N={N} beat {k} first")
            self.assertEqual(c["last"],  1 if k % nb == nb - 1 else 0,  f"N={N} beat {k} last")

    # verify-tier: model — flattened lanes bit-identical to the serial scaled-mode FFT
    # (gateware co-simulation) and to parallel_fft_model/fft_fixed_model, framing checked.
    def test_bit_identical_to_serial(self):
        for N in [16, 64, 256]:
            self.check_bit_identical(N)

    # verify-tier: model — the commutator/FIFO/core state must advance only on real
    # transfers: identical frames under input gaps and output backpressure.
    def test_backpressure(self):
        self.check_bit_identical(64, throttle=0.3, ready=0.6)
        self.check_bit_identical(16, throttle=0.5, ready=0.4, nfr=5)

    # verify-tier: model — timing-oriented registered-rank/folded-core option retains every
    # serial fixed-point rounding boundary under stalls.
    def test_folded_cores_bit_identical(self):
        for N in [16, 64]:
            self.check_bit_identical(N, throttle=0.25, ready=0.65, nfr=4,
                core_architecture="folded")

    def test_invalid_params_rejected(self):
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=100, with_csr=False)          # Not a power of two.
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=4, with_csr=False)            # Below minimum size.
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=64, n_samples=4, with_csr=False)  # P=4 not landed yet.
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=64, core_architecture="unknown", with_csr=False)
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=64, implementation="unknown", with_csr=False)
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=64, n_samples=8, implementation="native", with_csr=False)
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=64, feedback_pipeline=True, with_csr=False)


class TestNativeParallelFFT(unittest.TestCase):
    """Architecture matrix for the native P-wide SDF cascade."""

    def test_pipelined_rank_matches_classic_rank(self):
        rng = np.random.RandomState(20260717)
        for N, stage, n_samples in [(16, 0, 2), (16, 1, 2), (32, 1, 4)]:
            with self.subTest(N=N, stage=stage, n_samples=n_samples):
                values_i = rng.randint(-25000, 25000, 4*N)
                values_q = rng.randint(-25000, 25000, 4*N)
                beats = [{"i": pack_lanes(values_i[k:k + n_samples]),
                          "q": pack_lanes(values_q[k:k + n_samples])}
                         for k in range(0, len(values_i), n_samples)]
                classic = _LiteDSPFFTVectorStage(N, stage, n_samples)
                piped   = _LiteDSPFFTVectorPipelinedStage(N, stage, n_samples)
                ref = run_stream(classic, beats, len(beats), ["i", "q"], ["i", "q"])
                got = run_stream(piped,   beats, len(beats), ["i", "q"], ["i", "q"])
                self.assertEqual(got, ref)

    def run_native(self, xi, xq, N, n_samples, n_frames, throttle=0.0, ready=1.0,
        feedback_pipeline=False):
        dut = LiteDSPParallelFFT(N=N, n_samples=n_samples, implementation="native",
            feedback_pipeline=feedback_pipeline, with_csr=False)
        beats = [{"i": pack_lanes(xi[k:k + n_samples]),
                  "q": pack_lanes(xq[k:k + n_samples])}
                 for k in range(0, len(xi), n_samples)]
        return dut, run_stream(dut, beats, n_frames*N//n_samples, ["i", "q"],
            ["i", "q", "first", "last"], sink_throttle=throttle,
            source_ready_rate=ready)

    def check_native(self, N, n_samples, throttle=0.0, ready=1.0, feedback_pipeline=False):
        nfr = 4
        rng  = np.random.RandomState(100*N + n_samples)
        xi   = rng.randint(-25000, 25000, nfr*N)
        xq   = rng.randint(-25000, 25000, nfr*N)
        _, cap = self.run_native(xi, xq, N, n_samples, nfr - 1, throttle, ready,
            feedback_pipeline=feedback_pipeline)
        gi, gq = flatten(cap, "i", n_samples), flatten(cap, "q", n_samples)
        for f in range(nfr - 1):
            ri, rq = fft_fixed_model(xi[f*N:(f + 1)*N], xq[f*N:(f + 1)*N])
            np.testing.assert_array_equal(gi[f*N:(f + 1)*N], ri,
                f"native P={n_samples} N={N} frame={f} I")
            np.testing.assert_array_equal(gq[f*N:(f + 1)*N], rq,
                f"native P={n_samples} N={N} frame={f} Q")
        frame_beats = N//n_samples
        for k, c in enumerate(cap):
            self.assertEqual(c["first"], int(k % frame_beats == 0))
            self.assertEqual(c["last"],  int(k % frame_beats == frame_beats - 1))

    # verify-tier: model — both native widths retain every serial SDF rounding boundary.
    def test_bit_identical_architecture_matrix(self):
        for n_samples in [2, 4]:
            for N in [16, 64, 256]:
                with self.subTest(n_samples=n_samples, N=N):
                    self.check_native(N, n_samples)

    # verify-tier: model — registered multiplier ranks and their same-address forwarding retain
    # the native engine's exact per-rank rounding and full P-wide rate.
    def test_feedback_pipeline_bit_identical(self):
        for n_samples in [2, 4]:
            for N in [16, 64, 256]:
                with self.subTest(n_samples=n_samples, N=N):
                    self.check_native(N, n_samples, feedback_pipeline=True)

    # verify-tier: model — vector feedback and the lane realigner advance only on transfers.
    def test_backpressure_architecture_matrix(self):
        for n_samples in [2, 4]:
            for feedback_pipeline in [False, True]:
                with self.subTest(n_samples=n_samples, feedback_pipeline=feedback_pipeline):
                    self.check_native(64, n_samples, throttle=0.3, ready=0.55,
                        feedback_pipeline=feedback_pipeline)

    # verify-tier: model — P samples are accepted/emitted every free-flow clock and the
    # first-frame latency contract is cycle-exact for P=2 and P=4.
    def test_sustained_native_rate_and_latency(self):
        for n_samples in [2, 4]:
            for N in [16, 64]:
                for feedback_pipeline in [False, True]:
                    with self.subTest(n_samples=n_samples, N=N,
                        feedback_pipeline=feedback_pipeline):
                        self.check_native_rate(N, n_samples, feedback_pipeline)

    def check_native_rate(self, N, n_samples, feedback_pipeline):
        dut = LiteDSPParallelFFT(N=N, n_samples=n_samples,
            implementation="native", feedback_pipeline=feedback_pipeline,
            with_csr=False)
        values = np.arange(3*N)
        beats  = [pack_lanes(values[k:k + n_samples])
                  for k in range(0, len(values), n_samples)]
        stats = {"first_in": None, "out_cycles": []}

        @passive
        def driver():
            cycle, index = 0, 0
            yield dut.sink.valid.eq(1)
            yield dut.sink.i.eq(beats[0])
            yield dut.sink.q.eq(0)
            while True:
                yield
                cycle += 1
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    if stats["first_in"] is None:
                        stats["first_in"] = cycle
                    index += 1
                    if index < len(beats):
                        yield dut.sink.i.eq(beats[index])
                    else:
                        yield dut.sink.valid.eq(0)

        def capture():
            cycle = 0
            yield dut.source.ready.eq(1)
            while len(stats["out_cycles"]) < N//n_samples:
                yield
                cycle += 1
                if (yield dut.source.valid):
                    stats["out_cycles"].append(cycle)

        run_simulation(dut, [driver(), capture()])
        self.assertEqual(stats["out_cycles"][0] - stats["first_in"], dut.latency)
        np.testing.assert_array_equal(np.diff(stats["out_cycles"]),
            np.ones(N//n_samples - 1, dtype=int))
        self.assertEqual(dut.peak_samples_per_cycle, n_samples)
        self.assertEqual(dut.average_samples_per_cycle, n_samples)

# Throughput / Latency -----------------------------------------------------------------------------

class TestParallelFFTThroughput(unittest.TestCase):
    # verify-tier: model — sustained 2 samples/cycle free-flow (cycle-count assertion: every
    # output beat on consecutive cycles, frames back-to-back) and declared latency cycle-exact.
    def test_sustained_two_samples_per_cycle(self):
        for N in [16, 64, 256]:
            with self.subTest(N=N):
                self.check_throughput(N)

    # verify-tier: model — the registered-rank/folded-core configuration pins its declared
    # first-frame latency and exposes the intentional 2-wide peak / 1-sample-clock average.
    def test_folded_latency_and_rate_contract(self):
        for N in [16, 64]:
            with self.subTest(N=N):
                dut = LiteDSPParallelFFT(N=N, core_architecture="folded", with_csr=False)
                nfr = 5
                values = np.arange(nfr*N)
                beats = [(pack_lanes(values[k:k + 2]), 0) for k in range(0, len(values), 2)]
                stats = {"first_in": None, "out_cycles": []}

                @passive
                def driver():
                    cycle = 0
                    idx   = 0
                    yield dut.sink.valid.eq(1)
                    yield dut.sink.i.eq(beats[0][0])
                    yield dut.sink.q.eq(0)
                    while True:
                        yield
                        cycle += 1
                        if (yield dut.sink.valid) and (yield dut.sink.ready):
                            if stats["first_in"] is None:
                                stats["first_in"] = cycle
                            idx += 1
                            if idx < len(beats):
                                yield dut.sink.i.eq(beats[idx][0])
                            else:
                                yield dut.sink.valid.eq(0)

                def capture():
                    cycle = 0
                    yield dut.source.ready.eq(1)
                    while len(stats["out_cycles"]) < N//2:
                        yield
                        cycle += 1
                        if (yield dut.source.valid):
                            stats["out_cycles"].append(cycle)

                run_simulation(dut, [driver(), capture()])
                self.assertEqual(stats["out_cycles"][0] - stats["first_in"], dut.latency)
                np.testing.assert_array_equal(np.diff(stats["out_cycles"]),
                    np.ones(N//2 - 1, dtype=int))
                self.assertEqual(dut.peak_samples_per_cycle, 2)
                self.assertEqual(dut.average_samples_per_cycle, 1)

    def check_throughput(self, N, nfr=5):
        dut = LiteDSPParallelFFT(N=N, with_csr=False)
        rng = np.random.RandomState(N + 7)
        xi  = rng.randint(-25000, 25000, nfr*N)
        xq  = rng.randint(-25000, 25000, nfr*N)
        beats = [(pack_lanes(xi[k:k + 2]), pack_lanes(xq[k:k + 2]))
                 for k in range(0, len(xi), 2)]
        stats = {"first_in": None, "out_cycles": []}

        @passive
        def driver():
            cycle = 0
            idx   = 0
            yield dut.sink.valid.eq(1)
            yield dut.sink.i.eq(beats[0][0])
            yield dut.sink.q.eq(beats[0][1])
            while True:
                yield
                cycle += 1
                if (yield dut.sink.ready) and (yield dut.sink.valid):
                    if stats["first_in"] is None:
                        stats["first_in"] = cycle
                    idx += 1
                    if idx < len(beats):
                        yield dut.sink.i.eq(beats[idx][0])
                        yield dut.sink.q.eq(beats[idx][1])
                    else:
                        yield dut.sink.valid.eq(0)

        def capture():
            cycle = 0
            yield dut.source.ready.eq(1)
            while len(stats["out_cycles"]) < (nfr - 1)*N//2:
                yield
                cycle += 1
                if (yield dut.source.valid):
                    stats["out_cycles"].append(cycle)

        run_simulation(dut, [driver(), capture()])
        cycles = np.array(stats["out_cycles"])
        # Declared latency is cycle-exact (first input beat accepted -> first output beat).
        self.assertEqual(int(cycles[0]) - stats["first_in"], dut.latency,
            f"N={N}: measured latency {int(cycles[0]) - stats['first_in']} != {dut.latency}")
        # Sustained 2 samples/cycle: every output beat (2 samples) on consecutive cycles,
        # across frame boundaries, from the very first beat.
        gaps = np.diff(cycles)
        self.assertTrue(np.all(gaps == 1),
            f"N={N}: output not gap-free under free flow (max gap {int(gaps.max())})")

if __name__ == "__main__":
    unittest.main()
