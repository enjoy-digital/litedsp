#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import passive

from litedsp.comm.cfo_est   import LiteDSPCFOEstimator
from litedsp.correction.cfo import LiteDSPDerotator

from test.common import run_stream, column, to_signed
from test.models import cfo_estimator_model

# Helpers ------------------------------------------------------------------------------------------

@passive
def estimate_monitor(dut, results):
    """Record (angle, phase_inc) on each estimate_ready pulse (latched the same edge)."""
    while True:
        if (yield dut.estimate_ready):
            results.append({
                "angle":     (yield dut.angle),
                "phase_inc": (yield dut.phase_inc_correction),
            })
        yield

def cfo_signal(n, delay, f, amp=12000, snr_db=None, seed=0):
    """Repeating random preamble (period ``delay``) with CFO ``f`` (cycles/sample) applied.

    Optional complex AWGN at ``snr_db`` relative to the constant-modulus signal power.
    Returns integer (i, q) sample lists, clipped to 16-bit.
    """
    rng  = np.random.default_rng(seed)
    base = amp*np.exp(1j*rng.uniform(0, 2*np.pi, delay))
    x    = np.tile(base, n//delay + 1)[:n]*np.exp(1j*2*np.pi*f*np.arange(n))
    if snr_db is not None:
        sigma = amp/np.sqrt(2*10**(snr_db/10))
        x     = x + sigma*(rng.standard_normal(n) + 1j*rng.standard_normal(n))
    xi = np.clip(np.round(x.real), -32768, 32767).astype(int)
    xq = np.clip(np.round(x.imag), -32768, 32767).astype(int)
    return list(xi), list(xq)

def run_estimator(dut, xi, xq, **kwargs):
    """Stream (xi, xq) through ``dut`` and return (passthrough capture, estimate list)."""
    est = []
    cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))], len(xi),
        ["i", "q"], ["i", "q"], extra=[estimate_monitor(dut, est)], **kwargs)
    return cap, est

class TestCFOEstimator(unittest.TestCase):
    # Angle truth/tolerance derivation (delay D, span N = 2**span_log2, angle_width aw):
    # each product r[n] = x[n]*conj(x[n-D]) of the period-D preamble has exact phase
    # 2*pi*f*D, so angle(R) truth in angle units is f*D*2**aw (f in cycles/sample); with
    # f = frac/(2*D) that is frac*2**(aw-1). The first span has M = N - D nonzero products
    # (zero-filled delay line), which scales |R| but not its angle.
    #
    # SNR = inf: the only errors are the int16 input rounding (<= 0.5 LSB on a 12000-amplitude
    # component, i.e. < 4e-5 rad per product, averaging down over M products) and the CORDIC
    # (angle_width-quantized atan LUT + aw stages: a few LSBs, see test_cordic). Gate at
    # 16 units = 16/2**16 of a circle (~1.5e-3 rad).
    TOL_INF = 16
    # SNR = 10 dB: delay-and-multiply angle variance ~ (1/M)*(1/rho + 1/(2*rho**2)) rad**2
    # (both product terms noisy; Kay/Fitz), rho = 10, M = 240 -> sigma = 0.0209 rad =
    # 218 angle units. Gate at 6*sigma ~ 1310 units (~2% of the +/-1/(2D) capture range);
    # the noise realization is a fixed-seed rng, so the test is deterministic.
    TOL_10DB = 1310

    # verify-tier: bound (SNR=inf: quantization; 10 dB: 6-sigma of the derived estimator
    # variance) — the model tier lives in test_bit_exact_vs_model_backpressure below.
    def test_known_cfo_accuracy(self):
        D, span_log2, aw = 16, 8, 16
        n = (1 << span_log2) + 32
        for snr_db, tol in ((None, self.TOL_INF), (10, self.TOL_10DB)):
            for frac in (-0.9, -0.5, -0.1, 0.1, 0.5, 0.9):
                with self.subTest(cfo_frac=frac, snr_db=snr_db or "inf"):
                    f = frac/(2*D)
                    xi, xq = cfo_signal(n, D, f, snr_db=snr_db, seed=42)
                    dut = LiteDSPCFOEstimator(data_width=16, delay=D, span_log2=span_log2,
                        angle_width=aw, with_csr=False)
                    _, est = run_estimator(dut, xi, xq,
                        sink_throttle=0.0, source_ready_rate=1.0)
                    self.assertGreaterEqual(len(est), 1)
                    ang   = int(to_signed(est[0]["angle"], aw))
                    truth = frac*(1 << (aw - 1))
                    self.assertLess(abs(ang - truth), tol,
                        f"angle {ang} vs truth {truth:.1f} (tol {tol})")

    # verify-tier: bound — end-to-end acquisition: the estimated phase_inc_correction,
    # written to the derotator NCO, must cancel the CFO to < 1% of the +/-1/(2D) range.
    def test_estimate_to_derotator_closure(self):
        D, span_log2 = 16, 8
        f = 0.37/(2*D)                       # Off-grid CFO inside the capture range.
        n_est = (1 << span_log2) + 32
        xi, xq = cfo_signal(n_est, D, f, seed=7)
        est_dut = LiteDSPCFOEstimator(data_width=16, delay=D, span_log2=span_log2,
            with_csr=False)
        _, est = run_estimator(est_dut, xi, xq, sink_throttle=0.0, source_ready_rate=1.0)
        self.assertGreaterEqual(len(est), 1)
        phase_inc = est[0]["phase_inc"]

        # Apply the correction: derotate a fresh (longer) realization of the same channel.
        n = 1024
        yi, yq = cfo_signal(n, D, f, seed=7)
        der = LiteDSPDerotator(data_width=16, with_csr=False)
        der.nco.phase_inc.reset = phase_inc
        cap = run_stream(der, [{"i": yi[k], "q": yq[k]} for k in range(n)], n - 4,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = (column(cap, "i", 16) + 1j*column(cap, "q", 16))[32:]
        # Residual CFO via the same delay-D autocorrelation, measured in float.
        r_res = np.mean(y[D:]*np.conj(y[:-D]))
        f_res = np.angle(r_res)/(2*np.pi*D)
        self.assertLess(abs(f_res), 0.01*(1/(2*D)),
            f"residual CFO {f_res:.2e} cycles/sample after correction")

    # verify-tier: model — sample-domain datapath (exact accumulate + CORDIC recurrence):
    # estimates and the comb passthrough must be bit-exact vs the golden model under
    # randomized valid/ready stalls.
    def test_bit_exact_vs_model_backpressure(self):
        D, span_log2 = 8, 5
        N    = 1 << span_log2
        n    = 3*N + 60
        prng = random.Random(5)
        xi = [prng.randint(-20000, 20000) for _ in range(n)]
        xq = [prng.randint(-20000, 20000) for _ in range(n)]
        dut = LiteDSPCFOEstimator(data_width=16, delay=D, span_log2=span_log2, with_csr=False)
        cap, est = run_estimator(dut, xi, xq, sink_throttle=0.3, source_ready_rate=0.6)
        # Passthrough: unchanged payload, sample for sample.
        self.assertTrue(np.array_equal(column(cap, "i", 16), np.array(xi)))
        self.assertTrue(np.array_equal(column(cap, "q", 16), np.array(xq)))
        # Estimates: bit-exact vs the model (the simulation ends when the last passthrough
        # sample is captured, so the final in-flight CORDIC result may not be observed).
        angles, phase_incs = cfo_estimator_model(xi, xq, delay=D, span_log2=span_log2)
        k = min(len(est), len(angles))
        self.assertGreaterEqual(k, 3)
        got_ang = [int(to_signed(e["angle"], 16)) for e in est[:k]]
        got_inc = [e["phase_inc"] for e in est[:k]]
        self.assertEqual(got_ang, angles[:k])
        self.assertEqual(got_inc, phase_incs[:k])

    def test_params(self):
        with self.assertRaises(ValueError):
            LiteDSPCFOEstimator(delay=12)                    # Not a power of two.
        with self.assertRaises(ValueError):
            LiteDSPCFOEstimator(delay=1)                     # Delay-line needs >= 2.
        with self.assertRaises(ValueError):
            LiteDSPCFOEstimator(span_log2=0)
        with self.assertRaises(ValueError):
            LiteDSPCFOEstimator(delay=256, angle_width=16, phase_bits=16)  # Shift < 0.

if __name__ == "__main__":
    unittest.main()
