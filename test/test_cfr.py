#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPCFR tests: bit-exact against ``cfr_model`` under backpressure (multi-peak random +
OFDM-like Gaussian I/Q), plus functional crest-factor gates (PAPR reduction, below-threshold
EVM, ACLR/spectral regrowth) measured on the model output — which the bit-exact tests tie to
the RTL — with an RTL spot-check.

verify-tier: model + bound
"""

import random
import unittest

import numpy as np

from migen import passive

from litedsp.level.cfr import LiteDSPCFR, cfr_pulse

from test.common import run_stream, column
from test.models import cfr_model

# Stimulus -------------------------------------------------------------------------------------------

def ofdm_like(n, bw=0.2, rms=4000, seed=0):
    """OFDM-like Gaussian I/Q: random-phase subcarriers over |f| <= bw (PAPR ~10-11 dB)."""
    rng  = np.random.default_rng(seed)
    X    = np.zeros(n, complex)
    f    = np.fft.fftfreq(n)
    used = np.abs(f) <= bw
    X[used] = np.exp(1j*rng.uniform(0, 2*np.pi, used.sum()))
    x  = np.fft.ifft(X)
    x *= rms/np.sqrt(np.mean(np.abs(x)**2))
    return np.round(x.real).astype(np.int64), np.round(x.imag).astype(np.int64)

def multi_peak(n, seed=7, floor=9000, spacing=37):
    """Moderate random I/Q with strong random-phase peaks injected every ``spacing`` samples."""
    prng = random.Random(seed)
    xi = [prng.randint(-floor, floor) for _ in range(n)]
    xq = [prng.randint(-floor, floor) for _ in range(n)]
    for p in range(30, n - 10, spacing):
        a, ph = prng.randint(15000, 32000), prng.random()*2*np.pi
        xi[p], xq[p] = int(a*np.cos(ph)), int(a*np.sin(ph))
    return xi, xq

# Metrics --------------------------------------------------------------------------------------------

def papr_db(i, q):
    p = np.asarray(i, float)**2 + np.asarray(q, float)**2
    return 10*np.log10(p.max()/p.mean())

def psd_ratio_db(i, q, bw=0.2, guard=0.05, nfft=1024):
    """In-band to out-of-band mean PSD ratio (ACLR-style, Hann-windowed segment average)."""
    x    = np.asarray(i, float) + 1j*np.asarray(q, float)
    segs = len(x)//nfft
    w    = np.hanning(nfft)
    P    = np.zeros(nfft)
    for s in range(segs):
        P += np.abs(np.fft.fft(x[s*nfft:(s + 1)*nfft]*w))**2
    f = np.fft.fftfreq(nfft)
    return 10*np.log10(P[np.abs(f) <= bw].mean()/P[np.abs(f) >= bw + guard].mean())

def evm_below_pct(in_i, in_q, out_i, out_q, threshold, delay):
    """RMS error of the below-threshold (true-magnitude) samples vs the delayed input, %RMS."""
    n      = len(out_i) - delay
    xi, xq = np.asarray(in_i, float)[:n], np.asarray(in_q, float)[:n]
    yi, yq = np.asarray(out_i, float)[delay:], np.asarray(out_q, float)[delay:]
    sel    = np.hypot(xi, xq) <= threshold
    err    = (yi - xi)[sel]**2 + (yq - xq)[sel]**2
    return 100*np.sqrt(err.mean()/np.mean(xi**2 + xq**2))

# Tests ----------------------------------------------------------------------------------------------

class TestCFR(unittest.TestCase):
    def run_cfr(self, xi, xq, threshold, pulse_span=16, cutoff=0.2, throttle=0.25,
        ready_rate=0.75, architecture="classic"):
        dut = LiteDSPCFR(data_width=16, pulse_span=pulse_span, threshold=threshold,
            cutoff=cutoff, architecture=architecture, with_csr=False)
        counts = {}

        @passive
        def watch():
            while True:
                counts["peaks"]  = (yield dut.peak_count)
                counts["missed"] = (yield dut.missed_count)
                yield

        cap = run_stream(dut, [{"i": int(a), "q": int(b)} for a, b in zip(xi, xq)],
            len(xi), ["i", "q"], ["i", "q"], sink_throttle=throttle,
            source_ready_rate=ready_rate, extra=[watch()])
        return column(cap, "i", 16), column(cap, "q", 16), counts

    # verify-tier: model — coefficient pipelining preserves cancellation arithmetic and
    # sample-domain busy/reservation behavior under stalls; only the matched delay grows.
    def test_pipelined_bit_exact(self):
        xi, xq = multi_peak(700, seed=91, spacing=29)
        thr = 13500
        gi, gq, counts = self.run_cfr(xi, xq, thr, architecture="pipelined",
            throttle=0.3, ready_rate=0.65)
        ri, rq, peaks, missed = cfr_model(xi, xq, thr, cfr_pulse(16, cutoff=0.2),
            pipeline=3, correction_pipeline=True)
        np.testing.assert_array_equal(gi, ri)
        np.testing.assert_array_equal(gq, rq)
        self.assertEqual((counts["peaks"], counts["missed"]), (peaks, missed))
        self.assertEqual(LiteDSPCFR(architecture="pipelined", with_csr=False).delay,
            16//2 + 2 + 4)

    def test_invalid_architecture(self):
        with self.assertRaises(ValueError):
            LiteDSPCFR(architecture="invalid", with_csr=False)

    # verify-tier: model — the whole datapath (magnitude estimate, local-max detection,
    # reciprocal-LUT coefficient, pulse engine, busy-skip) advances on accepted samples only,
    # so the trajectory is handshake-invariant and bit-exact against cfr_model, counters
    # included.
    def test_bit_exact_multi_peak_random(self):
        for thr in [11000, 14000, 20000]:
            xi, xq = multi_peak(500, seed=thr)
            gi, gq, counts = self.run_cfr(xi, xq, thr)
            ri, rq, peaks, missed = cfr_model(xi, xq, thr, cfr_pulse(16, cutoff=0.2))
            self.assertTrue(np.array_equal(gi, ri), f"I mismatch thr={thr}")
            self.assertTrue(np.array_equal(gq, rq), f"Q mismatch thr={thr}")
            self.assertEqual(counts["peaks"],  peaks,  f"peak counter thr={thr}")
            self.assertEqual(counts["missed"], missed, f"missed counter thr={thr}")

    # verify-tier: model — same contract under an OFDM-like Gaussian load with heavy
    # throttle/backpressure and a longer pulse.
    def test_bit_exact_ofdm_backpressure(self):
        xi, xq = ofdm_like(1500, seed=3)
        rms = np.sqrt(np.mean(xi.astype(float)**2 + xq.astype(float)**2))
        thr = int(round(rms*10**(7.0/20)))                   # ~7 dB PAPR target.
        gi, gq, counts = self.run_cfr(xi, xq, thr, pulse_span=32, throttle=0.3, ready_rate=0.7)
        ri, rq, peaks, missed = cfr_model(xi, xq, thr, cfr_pulse(32, cutoff=0.2))
        self.assertTrue(np.array_equal(gi, ri), "I mismatch")
        self.assertTrue(np.array_equal(gq, rq), "Q mismatch")
        self.assertEqual((counts["peaks"], counts["missed"]), (peaks, missed))
        self.assertGreater(peaks, 0, "stimulus fired no peaks")

    # verify-tier: model — an isolated peak is cancelled down to ~threshold, centered
    # self.delay samples into the output (delay line + lookahead alignment).
    def test_peak_alignment_and_depth(self):
        n, n0, A, thr = 128, 60, 30000, 12000
        xi = [1000]*n
        xq = [0]*n
        xi[n0] = A                                           # mag estimate = A exactly (q = 0).
        dut_delay = LiteDSPCFR(data_width=16, threshold=thr, with_csr=False).delay
        gi, gq, counts = self.run_cfr(xi, xq, thr)
        self.assertEqual(counts["peaks"], 1)
        # The corrected peak emerges at out[n0 + delay]: |out| ~ threshold (LUT error <1%).
        got = gi[n0 + dut_delay]
        self.assertLess(abs(int(got) - thr), int(0.01*A) + 4,
            f"cancelled peak {got} not within ~1% of threshold {thr}")
        # And it is the deepest correction (pulse centered on the peak).
        ri, rq, _, _ = cfr_model(xi, xq, thr, cfr_pulse(16, cutoff=0.2))
        self.assertTrue(np.array_equal(gi, ri))
        diff = np.abs(np.array(xi[:n - dut_delay]) - gi[dut_delay:])
        self.assertEqual(int(np.argmax(diff)), n0)

    # verify-tier: bound — functional crest-factor gates on the model output (held bit-exact
    # to the RTL by the tests above). Measured with this exact stimulus (seed=1, 32768
    # samples, |f| <= 0.2, threshold at the 7 dB PAPR target): input PAPR 10.99 dB, output
    # PAPR 9.06 dB (1.93 dB reduction), below-threshold EVM 1.72% (-35.3 dB), in/out-of-band
    # PSD ratio 83.7 -> 61.7 dB. Gates sit ~3 dB under the measured values (PAPR reduction
    # gated at half, floors kept meaningful).
    def test_functional_gates_model(self):
        span   = 16
        xi, xq = ofdm_like(32768, bw=0.2, rms=4000, seed=1)
        rms    = np.sqrt(np.mean(xi.astype(float)**2 + xq.astype(float)**2))
        thr    = int(round(rms*10**(7.0/20)))                # ~7 dB PAPR target.
        oi, oq, peaks, missed = cfr_model(xi, xq, thr, cfr_pulse(span, cutoff=0.2))
        D        = span//2 + 2
        papr_in  = papr_db(xi, xq)
        papr_out = papr_db(oi[D:], oq[D:])
        self.assertGreater(papr_in, 10.0)                    # Gaussian-like stimulus sanity.
        self.assertLess(papr_in, 12.0)
        # PAPR: measured 10.99 -> 9.06 dB; gate at >= 0.9 dB reduction (half the measured).
        self.assertLessEqual(papr_out, papr_in - 0.9,
            f"PAPR {papr_in:.2f} -> {papr_out:.2f} dB: reduction below gate")
        # EVM of the below-threshold samples: measured 1.72%; gate 3 dB under (x sqrt(2)).
        evm = evm_below_pct(xi, xq, oi, oq, thr, D)
        self.assertLessEqual(evm, 2.5, f"below-threshold EVM {evm:.2f}% > 2.5%")
        # ACLR/spectral regrowth: measured 61.7 dB in/out-of-band ratio; gate 3 dB under.
        aclr = psd_ratio_db(oi[D:], oq[D:])
        self.assertGreaterEqual(aclr, 58.7, f"out-of-band regrowth: PSD ratio {aclr:.1f} dB")
        self.assertGreater(peaks, 100)                       # The engine actually worked.
        self.assertLess(missed, peaks//4)                    # Busy-skips stay the exception.

    # verify-tier: bound — RTL spot-check of the functional behavior (short record, free
    # flow): PAPR must drop and the spectrum must stay contained.
    def test_functional_rtl_spot_check(self):
        xi, xq = ofdm_like(4096, seed=2)
        rms = np.sqrt(np.mean(xi.astype(float)**2 + xq.astype(float)**2))
        thr = int(round(rms*10**(7.0/20)))
        gi, gq, counts = self.run_cfr(xi, xq, thr, throttle=0.0, ready_rate=1.0)
        D = 16//2 + 2
        self.assertLess(papr_db(gi[D:], gq[D:]), papr_db(xi, xq) - 0.5)
        self.assertGreaterEqual(psd_ratio_db(gi[D:], gq[D:]), 40.0)
        self.assertGreater(counts["peaks"], 0)

if __name__ == "__main__":
    unittest.main()
