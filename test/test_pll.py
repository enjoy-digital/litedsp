#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.comm.pll import LiteDSPCarrierLoop, LiteDSPPLL, LiteDSPCostas, LiteDSPQPSKCostas

from test.common import run_stream, column

# Loop bound derivation (kp_shift=4, ki_shift=12, phase_bits P=32, data_width D=16, amplitude A):
# the detector output is ~A*sin(phase_error) counts, scaled by 2**(P-D) into phase-rate units, so
# the per-sample loop gains are gp = A*2pi*2**-(D+kp_shift) (~0.07 for A~12000) and
# gi = A*2pi*2**-(D+ki_shift). The loop is overdamped (gp**2 >> 4*gi); the dominant (frequency)
# pole is gi/gp, i.e. tau = 2**(ki_shift-kp_shift) = 256 samples, independent of A. Bounds:
# - Lock time: |phase error| < 0.05 rad within LOCK_BOUND = 6*tau samples (measured ~730 for the
#   PLL, ~590 for Costas, at LITEDSP_SEED=0).
# - Post-lock jitter: set by the NCO LUT phase quantization q = 2pi/lut_depth = 2pi/1024:
#   RMS ~ q/sqrt(12) = 1.8e-3 rad; gate at ~2x (measured 1.8e-3 rad for both loops).
LOCK_BOUND = 6*(1 << (12 - 4))   # 6*tau = 1536 samples.
RMS_BOUND  = 4e-3                # rad, ~2x the LUT quantization floor 2pi/1024/sqrt(12).

def lock_time(phe, thresh=0.05):
    """First sample index after which |phase error| stays below ``thresh`` (rad) forever."""
    late = np.nonzero(np.abs(phe) >= thresh)[0]
    return 0 if len(late) == 0 else int(late[-1]) + 1

class TestPLL(unittest.TestCase):
    # verify-tier: bound — lock time and post-lock RMS phase error derived from kp/ki (above).
    def test_locks_to_tone(self):
        n = 8000
        f = 0.01
        x = 12000*np.exp(1j*2*np.pi*f*np.arange(n))
        dut = LiteDSPPLL(data_width=16, kp_shift=4, ki_shift=12, with_csr=False)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        tail = y[3*n//4:]                                # After lock.
        # Derotated tone should sit at a near-constant phase (low AC vs DC).
        self.assertGreater(np.abs(tail.mean()), 8000)
        self.assertLess(tail.std(), np.abs(tail.mean())/4)
        # Phase error vs the settled constellation angle: bounded lock time + post-lock jitter.
        phe = np.angle(y*np.exp(-1j*np.angle(tail.mean())))
        self.assertLess(lock_time(phe), LOCK_BOUND)
        self.assertLess(np.sqrt(np.mean(phe[3*n//4:]**2)), RMS_BOUND)

class TestCostas(unittest.TestCase):
    # verify-tier: bound — same loop constants as the PLL, same lock-time/jitter bounds; the
    # BPSK modulation is wiped with the known data so the residual is pure phase error.
    def test_recovers_bpsk(self):
        n = 12000
        f = 0.005
        rng = np.random.RandomState(0)
        bits = rng.randint(0, 2, n)
        data = 2*bits - 1                                 # +/-1 BPSK.
        x = 11000*data*np.exp(1j*2*np.pi*f*np.arange(n))
        dut = LiteDSPCostas(data_width=16, kp_shift=4, ki_shift=12, with_csr=False)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        yc = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        di = yc.real.astype(float)[3*n//4:]
        dq = yc.imag.astype(float)[3*n//4:]
        # After lock: data on I (large |I|), quadrature noise small.
        self.assertGreater(np.abs(di).mean(), 6000)
        self.assertLess(np.abs(dq).mean(), np.abs(di).mean()/4)
        # Recovered bits (sign of I) match data up to a global sign ambiguity.
        rec = (di >= 0).astype(int)
        ref = bits[3*n//4:3*n//4 + len(rec)]
        agree = np.mean(rec == ref)
        self.assertTrue(agree > 0.97 or agree < 0.03)    # BPSK sign ambiguity.
        # Wipe the modulation with the known data; the global sign ambiguity folds into the
        # settled constellation angle. Bounded lock time + post-lock jitter (derivation above).
        z   = yc*data[:len(yc)]
        phe = np.angle(z*np.exp(-1j*np.angle(z[3*n//4:].mean())))
        self.assertLess(lock_time(phe), LOCK_BOUND)
        self.assertLess(np.sqrt(np.mean(phe[3*n//4:]**2)), RMS_BOUND)

class TestQPSKCostas(unittest.TestCase):
    # verify-tier: bound — the sign(I)*Q-sign(Q)*I detector removes random QPSK data without
    # multipliers. Wiping the known symbols leaves the recovered carrier up to a quadrant.
    def test_recovers_qpsk(self):
        n = 12000
        f = 0.004
        rng = np.random.RandomState(2)
        data = (2*rng.randint(0, 2, n) - 1) + 1j*(2*rng.randint(0, 2, n) - 1)
        x = 7600*data*np.exp(1j*2*np.pi*f*np.arange(n))
        dut = LiteDSPQPSKCostas(data_width=16, kp_shift=5, ki_shift=13, with_csr=False)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        yc = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        z = yc*np.conj(data[:len(yc)])
        tail = z[3*n//4:]
        self.assertGreater(np.abs(tail.mean()), 9000)
        phe = np.angle(z*np.exp(-1j*np.angle(tail.mean())))
        self.assertLess(lock_time(phe), 6*(1 << (13 - 5)))
        self.assertLess(np.sqrt(np.mean(phe[3*n//4:]**2)), 6e-3)

    def test_invalid_detector(self):
        with self.assertRaises(ValueError):
            LiteDSPCarrierLoop(detector="invalid", with_csr=False)

if __name__ == "__main__":
    unittest.main()
