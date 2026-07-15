#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the 2-samples/cycle parallel FFT (litedsp/analysis/fft_parallel.py).

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
from litedsp.analysis.fft_parallel import LiteDSPParallelFFT

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
    def run_parallel(self, xi, xq, N, n_frames, throttle=0.0, ready=1.0):
        """Feed 2 samples/beat, capture ``n_frames`` output frames (i/q + framing markers).

        As with the serial SDF FFT, the pipeline holds about one frame (frame f streams out
        while frame f+1 streams in), so ``n_frames`` must leave the last input frame in
        flight (callers pass one frame more than they capture).
        """
        dut   = LiteDSPParallelFFT(N=N, with_csr=False)
        beats = [{"i": pack_lanes(xi[k:k + 2]), "q": pack_lanes(xq[k:k + 2])}
                 for k in range(0, len(xi), 2)]
        return run_stream(dut, beats, n_frames*N//2, ["i", "q"],
            ["i", "q", "first", "last"], sink_throttle=throttle, source_ready_rate=ready)

    def check_bit_identical(self, N, throttle=0.0, ready=1.0, nfr=4):
        rng = np.random.RandomState(N)
        xi  = rng.randint(-25000, 25000, nfr*N)
        xq  = rng.randint(-25000, 25000, nfr*N)
        cap = self.run_parallel(xi, xq, N, nfr - 1, throttle=throttle, ready=ready)
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

    def test_invalid_params_rejected(self):
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=100, with_csr=False)          # Not a power of two.
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=4, with_csr=False)            # Below minimum size.
        with self.assertRaises(ValueError):
            LiteDSPParallelFFT(N=64, n_samples=4, with_csr=False)  # P=4 not landed yet.

# Throughput / Latency -----------------------------------------------------------------------------

class TestParallelFFTThroughput(unittest.TestCase):
    # verify-tier: model — sustained 2 samples/cycle free-flow (cycle-count assertion: every
    # output beat on consecutive cycles, frames back-to-back) and declared latency cycle-exact.
    def test_sustained_two_samples_per_cycle(self):
        for N in [16, 64, 256]:
            with self.subTest(N=N):
                self.check_throughput(N)

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
