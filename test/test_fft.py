#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.analysis.fft import LiteDSPFFT, LiteDSPInterleavedFFT, bit_reverse

from test.common import run_stream, column, snr_db
from test.models import fft_model

def reorder_bitrev(frame, bits):
    """Reorder a bit-reversed FFT output frame into natural order."""
    return np.array([frame[bit_reverse(k, bits)] for k in range(len(frame))])

class TestFFT(unittest.TestCase):
    def run_fft(self, xi, xq, N, data_width=16, throttle=0.0, ready=1.0,
        architecture="classic"):
        dut = LiteDSPFFT(N=N, data_width=data_width, architecture=architecture, with_csr=False)
        samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))]
        captured = run_stream(dut, samples, len(xi) - 1, ["i", "q"], ["i", "q"],
            sink_throttle=throttle, source_ready_rate=ready)
        return column(captured, "i", data_width) + 1j*column(captured, "q", data_width)

    def best_frame_snr(self, out, ref, N, bits):
        best = -np.inf
        for off in range(len(out) - N):
            nat = reorder_bitrev(out[off:off + N], bits)
            best = max(best, snr_db(ref, nat))
        return best

    # Fixed-point bound: each radix-2 SDF stage halves the amplitude (1/N overall) and adds a
    # round-half-up step, so quantization noise accumulates and SNR falls with log2(N). Gates
    # are set 3 dB under the values measured at LITEDSP_SEED=0 (68.4/59.6/54.1 dB); the
    # capture is handshake-invariant, so the measurement is stable across seed rotation.
    SNR_GATES = {16: 65.0, 64: 56.5, 256: 51.0}

    # verify-tier: bound — per-size SNR against the fft_model golden reference.
    def test_random_snr(self):
        for N in [16, 64, 256]:
            bits = N.bit_length() - 1
            rng  = np.random.RandomState(N)
            fi   = rng.randint(-8000, 8000, N)
            fq   = rng.randint(-8000, 8000, N)
            nfr  = 6
            out  = self.run_fft(list(fi)*nfr, list(fq)*nfr, N)
            ref  = fft_model(fi, fq)
            snr  = self.best_frame_snr(out, ref, N, bits)
            self.assertGreater(snr, self.SNR_GATES[N], f"N={N} SNR={snr:.1f} dB")

    # verify-tier: bound — tone concentration + frame SNR (measured 79.7 dB; gate 3 dB under).
    def test_tone_bin(self):
        # A pure complex tone at bin k0 must concentrate energy in bin k0.
        N    = 64
        bits = 6
        k0   = 9
        t    = np.arange(N)
        fi   = np.round(10000*np.cos(2*np.pi*k0*t/N)).astype(int)
        fq   = np.round(10000*np.sin(2*np.pi*k0*t/N)).astype(int)
        out  = self.run_fft(list(fi)*6, list(fq)*6, N)
        ref  = fft_model(fi, fq)
        # Find aligned frame, check peak bin.
        best_off, best = 0, -np.inf
        for off in range(len(out) - N):
            nat = reorder_bitrev(out[off:off + N], bits)
            s   = snr_db(ref, nat)
            if s > best:
                best, best_off = s, off
        self.assertGreater(best, 76.5, f"tone frame SNR={best:.1f} dB")
        nat  = reorder_bitrev(out[best_off:best_off + N], bits)
        mag  = np.abs(nat)
        self.assertEqual(int(np.argmax(mag)), k0)
        self.assertGreater(mag[k0]/np.sort(mag)[-2], 50.0)  # >34 dB above next bin.

    # verify-tier: bound — same N=64 fixed-point bound as test_random_snr (measured 59.9 dB).
    def test_backpressure(self):
        # The SDF state must advance only on real transfers: result must survive stalls.
        N    = 64
        bits = 6
        rng  = np.random.RandomState(7)
        fi   = rng.randint(-8000, 8000, N)
        fq   = rng.randint(-8000, 8000, N)
        out  = self.run_fft(list(fi)*8, list(fq)*8, N, throttle=0.3, ready=0.6)
        ref  = fft_model(fi, fq)
        snr  = self.best_frame_snr(out, ref, N, bits)
        self.assertGreater(snr, self.SNR_GATES[N], f"backpressure SNR={snr:.1f} dB")

class TestFoldedFFT(unittest.TestCase):
    def capture(self, dut, xi, xq, n_out, throttle=0.0, ready=1.0):
        samples = [{"i": int(i), "q": int(q)} for i, q in zip(xi, xq)]
        cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
            sink_throttle=throttle, source_ready_rate=ready)
        return column(cap, "i", 16), column(cap, "q", 16)

    # verify-tier: model — folded stage boundaries change cycles only, never arithmetic.
    def test_bit_identical_to_classic(self):
        for N in [16, 64]:
            with self.subTest(N=N):
                rng = np.random.RandomState(100 + N)
                xi  = rng.randint(-25000, 25000, 5*N)
                xq  = rng.randint(-25000, 25000, 5*N)
                n   = len(xi) - 1
                ci, cq = self.capture(LiteDSPFFT(N=N, with_csr=False), xi, xq, n)
                fi, fq = self.capture(LiteDSPFFT(N=N, architecture="folded", with_csr=False),
                    xi, xq, n, throttle=0.3, ready=0.6)
                np.testing.assert_array_equal(fi, ci, f"N={N}: folded/classic I")
                np.testing.assert_array_equal(fq, cq, f"N={N}: folded/classic Q")

    # verify-tier: model — inverse twiddle convention is unchanged by folding.
    def test_inverse_bit_identical(self):
        N   = 16
        rng = np.random.RandomState(203)
        xi  = rng.randint(-20000, 20000, 5*N)
        xq  = rng.randint(-20000, 20000, 5*N)
        n   = len(xi) - 1
        ci, cq = self.capture(LiteDSPFFT(N=N, inverse=True, with_csr=False), xi, xq, n)
        fi, fq = self.capture(LiteDSPFFT(N=N, inverse=True, architecture="folded",
            with_csr=False), xi, xq, n)
        np.testing.assert_array_equal(fi, ci)
        np.testing.assert_array_equal(fq, cq)

    # verify-tier: model — free-flow folded input transfers are exactly two clocks apart.
    def test_sample_interval(self):
        dut   = LiteDSPFFT(N=16, architecture="folded", with_csr=False)
        stats = {"cycles": []}

        @passive
        def driver():
            cycle = 0
            yield dut.sink.valid.eq(1)
            yield dut.source.ready.eq(1)
            while len(stats["cycles"]) < 48:
                yield
                cycle += 1
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    stats["cycles"].append(cycle)

        def stop():
            while len(stats["cycles"]) < 48:
                yield

        run_simulation(dut, [driver(), stop()])
        np.testing.assert_array_equal(np.diff(stats["cycles"]), np.full(47, 2))
        self.assertEqual(dut.sample_interval, 2)

    def test_invalid_bfp_combination(self):
        with self.assertRaises(ValueError):
            LiteDSPFFT(N=16, scaling="bfp", architecture="folded", with_csr=False)

class TestInterleavedFFT(unittest.TestCase):
    # verify-tier: model — even/odd aggregate samples remain independent, bit-identical
    # folded streams under input gaps and output backpressure.
    def test_two_context_bit_identity(self):
        for N in [16, 64]:
            with self.subTest(N=N):
                rng = np.random.RandomState(300 + N)
                ai  = rng.randint(-24000, 24000, 5*N)
                aq  = rng.randint(-24000, 24000, 5*N)
                bi  = rng.randint(-24000, 24000, 5*N)
                bq  = rng.randint(-24000, 24000, 5*N)
                n_context = len(ai) - 1

                def folded_reference(xi, xq):
                    dut = LiteDSPFFT(N=N, architecture="folded", with_csr=False)
                    samples = [{"i": int(i), "q": int(q)} for i, q in zip(xi, xq)]
                    cap = run_stream(dut, samples, n_context, ["i", "q"], ["i", "q"],
                        sink_throttle=0.0, source_ready_rate=1.0)
                    return column(cap, "i", 16), column(cap, "q", 16)

                rai, raq = folded_reference(ai, aq)
                rbi, rbq = folded_reference(bi, bq)
                samples = []
                for k in range(len(ai)):
                    samples += [{"i": int(ai[k]), "q": int(aq[k])},
                                {"i": int(bi[k]), "q": int(bq[k])}]
                dut = LiteDSPInterleavedFFT(N=N, with_csr=False)
                cap = run_stream(dut, samples, 2*n_context, ["i", "q"], ["i", "q"],
                    sink_throttle=0.25, source_ready_rate=0.65)
                oi, oq = column(cap, "i", 16), column(cap, "q", 16)
                np.testing.assert_array_equal(oi[0::2], rai, f"N={N}: context 0 I")
                np.testing.assert_array_equal(oq[0::2], raq, f"N={N}: context 0 Q")
                np.testing.assert_array_equal(oi[1::2], rbi, f"N={N}: context 1 I")
                np.testing.assert_array_equal(oq[1::2], rbq, f"N={N}: context 1 Q")

    # verify-tier: model — two staggered contexts accept one aggregate sample each clock.
    def test_aggregate_sample_interval(self):
        dut   = LiteDSPInterleavedFFT(N=16, with_csr=False)
        stats = {"cycles": []}

        @passive
        def driver():
            cycle = 0
            yield dut.sink.valid.eq(1)
            yield dut.source.ready.eq(1)
            while len(stats["cycles"]) < 64:
                yield
                cycle += 1
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    stats["cycles"].append(cycle)

        def stop():
            while len(stats["cycles"]) < 64:
                yield

        run_simulation(dut, [driver(), stop()])
        np.testing.assert_array_equal(np.diff(stats["cycles"]), np.ones(63, dtype=int))
        self.assertEqual(dut.sample_interval, 1)

class TestIFFT(unittest.TestCase):
    # verify-tier: bound — N=64 inverse-FFT fixed-point bound (measured 57.0 dB at
    # LITEDSP_SEED=0; gate 3 dB under).
    def test_matches_numpy(self):
        N, bits = 64, 6
        rng = np.random.RandomState(0)
        X = (rng.randint(-6000, 6000, N) + 1j*rng.randint(-6000, 6000, N))
        dut = LiteDSPFFT(N=N, data_width=16, inverse=True, with_csr=False)
        samples = [{"i": int(X[k].real), "q": int(X[k].imag)} for k in range(N)]*5
        cap = run_stream(dut, samples, len(samples) - 1, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        out = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        ref = np.fft.ifft(X)
        best = -np.inf
        for off in range(len(out) - N):
            nat = reorder_bitrev(out[off:off + N], bits)
            best = max(best, snr_db(ref, nat))
        self.assertGreater(best, 54.0, f"IFFT SNR={best:.1f} dB")

if __name__ == "__main__":
    unittest.main()
