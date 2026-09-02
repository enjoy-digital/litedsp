#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.motor.observer import LiteDSPAngleTracker, LiteDSPSMObserver

from test.common import run_stream, stream_driver, stream_capture, column
from test.models import angle_tracker_model, smo_model, pmsm_steady_state

AW   = 16
TURN = 1 << AW
ONE  = 1 << 12                                    # 1.0 in Q4.12.
FS   = (1 << 15) - 1

def wrap_err(a, b):
    """Signed modular difference a - b in angle units."""
    return (np.asarray(a) - np.asarray(b) + TURN//2) % TURN - TURN//2

def deg(x):
    return x/TURN*360.0

class TestAngleTracker(unittest.TestCase):
    # verify-tier: model — wrapping loop arithmetic, bit-exact under backpressure with the
    # shift gains changed mid-stream (per-sample controls in the model).
    def test_bit_exact_under_backpressure(self):
        n, n_sw = 300, 150
        prng   = random.Random(1)
        angles = [prng.randint(-TURN//2, TURN//2 - 1) for _ in range(n)]
        dut = LiteDSPAngleTracker(angle_width=AW, kp_shift=4, ki_shift=10, with_csr=False)
        dut.angle_offset.reset = 1234

        @passive
        def switch():
            accepted = 0
            while accepted < n_sw:
                yield
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    accepted += 1
            yield dut.kp_shift.eq(3)
            yield dut.ki_shift.eq(8)
            while True:
                yield

        cap = run_stream(dut, [{"angle": a} for a in angles], n, ["angle"], ["angle"],
            sink_throttle=0.2, source_ready_rate=0.7, extra=[switch()])
        ref, _ = angle_tracker_model(angles, np.array([4]*n_sw + [3]*(n - n_sw)),
            np.array([10]*n_sw + [8]*(n - n_sw)), angle_offset=1234)
        self.assertTrue(np.array_equal(column(cap, "angle", AW), ref))
        self.assertEqual(dut.latency, 1)

    # verify-tier: bound — a constant-speed ramp (500 units/sample) with +/-300 uniform noise:
    # type-II loop, so the tracked angle converges with zero steady-state error. Lock (error
    # < 3 degrees) within 6*2**(ki-kp) = 384 samples as for the carrier loop (test_pll);
    # post-lock RMS error vs the clean ramp is the input noise (sigma 173 units = 0.95
    # degrees) filtered by the loop (kp = 2**-4: ~1/sqrt(8)), ~0.35 degrees (measured value
    # at LITEDSP_SEED=0 in the assertion message; gate 1.0). Speed = 500 << frac within 1 %.
    def test_locks_to_ramp(self):
        n, step, frac = 4000, 500, 14
        prng  = random.Random(2)
        truth = (np.arange(n)*step) % TURN
        noisy = [(int(t) + prng.randint(-300, 300)) % TURN for t in truth]
        noisy = [a - TURN if a >= TURN//2 else a for a in noisy]
        dut = LiteDSPAngleTracker(angle_width=AW, frac_bits=frac, kp_shift=4, ki_shift=10,
            with_csr=False)
        speeds = []

        @passive
        def watch():
            while True:
                speeds.append((yield dut.speed))
                yield

        cap = run_stream(dut, [{"angle": a} for a in noisy], n, ["angle"], ["angle"],
            sink_throttle=0.0, source_ready_rate=1.0, extra=[watch()])
        out = column(cap, "angle", AW) % TURN
        err = deg(wrap_err(out, truth))
        late = np.nonzero(np.abs(err) >= 3.0)[0]
        self.assertLess(int(late[-1]) + 1 if len(late) else 0, 6*(1 << (10 - 4)))
        rms = np.sqrt(np.mean(err[n//2:]**2))
        self.assertLess(rms, 1.0, f"post-lock RMS {rms:.2f} deg")
        speed = speeds[-1] - (1 << dut.loop_width) if speeds[-1] >= (1 << (dut.loop_width - 1)) else speeds[-1]
        self.assertLess(abs(speed - (step << frac)), 0.01*(step << frac))

    def test_wraps_across_pi(self):
        # A ramp crossing +pi -> -pi several times: no glitch (error stays small after lock).
        n, step = 3000, 1500
        truth = (np.arange(n)*step) % TURN
        angles = [int(t) - TURN if t >= TURN//2 else int(t) for t in truth]
        dut = LiteDSPAngleTracker(angle_width=AW, with_csr=False)
        cap = run_stream(dut, [{"angle": a} for a in angles], n, ["angle"], ["angle"],
            sink_throttle=0.0, source_ready_rate=1.0)
        err = deg(wrap_err(column(cap, "angle", AW) % TURN, truth))
        self.assertLess(np.max(np.abs(err[1000:])), 1.0)

    def test_invalid(self):
        for kwargs in ({"kp_shift": 32}, {"frac_bits": -1}, {"angle_width": 2}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPAngleTracker(with_csr=False, **kwargs)

def run_smo(dut, i_a, i_b, v_a, v_b, n, throttle=(0.2, 0.3), ready_rate=0.7, extra=None):
    captured = []
    run_simulation(dut, [
        stream_driver(dut.sink_i, [{"i": int(a), "q": int(b)} for a, b in zip(i_a, i_b)],
            ["i", "q"], seed=3, throttle=throttle[0]),
        stream_driver(dut.sink_v, [{"i": int(a), "q": int(b)} for a, b in zip(v_a, v_b)],
            ["i", "q"], seed=4, throttle=throttle[1]),
        stream_capture(dut.source, captured, n, ["angle"], seed=5, ready_rate=ready_rate),
    ] + (extra or []))
    return column(captured, "angle", AW)

def lpf_lag(dtheta, lpf_shift):
    """Phase lag (radians) of the one-pole back-EMF filter at ``dtheta`` rad/sample."""
    a = 1 - 2.0**-lpf_shift
    return np.arctan2(a*np.sin(dtheta), 1 - a*np.cos(dtheta))

class TestSMObserver(unittest.TestCase):
    GAINS = dict(g_v=int(round(0.1/0.3*ONE)), g_r=int(round(0.05*0.1/0.3*ONE)),
        k_sm=int(0.3*FS), lpf_shift=3)                    # L_pu 0.3, R_pu 0.05, w_b*Ts 0.1.

    @staticmethod
    def gains(omega):
        """Operating-point gains: sliding gain ~0.35*w (half the back-EMF, psi = 0.6)."""
        g = dict(TestSMObserver.GAINS)
        g.update(k_sm=int(0.35*omega*FS), lpf_shift=4)
        return g

    def build(self, gains=None, **kwargs):
        dut = LiteDSPSMObserver(data_width=16, angle_width=AW, with_csr=False, **kwargs)
        for k, v in (gains or self.GAINS).items():
            getattr(dut, k).reset = v
        return dut

    # verify-tier: model — sign-based sliding term, LPF, current model and CORDIC vectoring on
    # the updated EMF, bit-exact under independently throttled sinks.
    def test_bit_exact_under_backpressure(self):
        n    = 300
        prng = random.Random(6)
        cols = [[prng.randint(-20000, 20000) for _ in range(n)] for _ in range(4)]
        dut  = self.build()
        got  = run_smo(dut, *cols, n)
        ref  = smo_model(*cols, **self.GAINS)
        self.assertTrue(np.array_equal(got, ref))
        self.assertEqual(dut.latency, 19)

    # verify-tier: bound — steady-state PMSM (i_q = 0.5 pu) at 0.3 and 0.8 pu speed with the
    # operating-point sliding gain (0.35*w) and lpf_shift = 4: the raw angle lags the rotor by
    # a positive constant bounded by the back-EMF filter phase atan2(a*sin(d), 1 - a*cos(d))
    # (a = 1 - 2**-lpf_shift, d = angle step per sample: 24.1 / 48.8 degrees; the current
    # model loop partly compensates it -- measured 12.9 / 33.6 degrees on the model), does
    # not drift (two halves within 2 degrees) and the residual chatter has RMS < 5 degrees
    # (measured 2.5 / 3.2).
    def test_tracks_pmsm_steady_state(self):
        n = 1500
        for omega in (0.3, 0.8):
            with self.subTest(omega=omega):
                i_a, i_b, v_a, v_b, theta = pmsm_steady_state(omega, 0.5, n=n)
                got = run_smo(self.build(self.gains(omega)), i_a, i_b, v_a, v_b, n,
                    throttle=(0.0, 0.0), ready_rate=1.0)
                err = wrap_err(got % TURN, theta % TURN)[n//2:]
                lag = np.degrees(-np.mean(err)/TURN*2*np.pi)
                self.assertGreater(lag, 0.0, f"lag {lag:.1f} deg")
                self.assertLess(lag, np.degrees(lpf_lag(omega*0.1, 4)) + 5.0, f"lag {lag:.1f} deg")
                self.assertLess(abs(deg(np.mean(err[:len(err)//2]) - np.mean(err[len(err)//2:]))), 2.0)
                rms = deg(np.sqrt(np.mean((err - np.mean(err))**2)))
                self.assertLess(rms, 5.0, f"residual RMS {rms:.2f} deg")

    # verify-tier: bound — observer -> tracker chain at 0.5 pu (gains as above): the tracked
    # angle keeps the observer's constant lag (bounded by the filter phase, 36.5 degrees) with
    # an RMS residual below 3 degrees (the type-II loop filters the chatter).
    def test_with_tracker_lock(self):
        n = 2000

        class Chain(LiteXModule):
            def __init__(self, smo):
                self.smo     = smo
                self.tracker = LiteDSPAngleTracker(angle_width=AW, kp_shift=3, ki_shift=8,
                    with_csr=False)
                self.sink_i, self.sink_v, self.source = smo.sink_i, smo.sink_v, self.tracker.source
                self.comb += smo.source.connect(self.tracker.sink)

        i_a, i_b, v_a, v_b, theta = pmsm_steady_state(0.5, 0.5, n=n)
        got = run_smo(Chain(self.build(self.gains(0.5))), i_a, i_b, v_a, v_b, n,
            throttle=(0.0, 0.0), ready_rate=1.0)
        err = wrap_err(got % TURN, theta % TURN)[n//2:]
        lag = np.degrees(-np.mean(err)/TURN*2*np.pi)
        self.assertTrue(0.0 < lag < np.degrees(lpf_lag(0.05, 4)) + 5.0, f"lag {lag:.1f} deg")
        rms = deg(np.sqrt(np.mean((err - np.mean(err))**2)))
        self.assertLess(rms, 3.0, f"residual RMS {rms:.2f} deg")

    def test_invalid(self):
        for kwargs in ({"stages": 0}, {"gain_frac": 16}, {"data_width": 2}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPSMObserver(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
