#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.motor.foc import LiteDSPFOC

from test.common import stream_driver, stream_capture, column
from test.models import foc_model, svpwm_model, inverse_park_model

AW   = 16
TURN = 1 << AW
FS   = (1 << 15) - 1
ONE  = 1 << 12

@passive
def watchdog(limit):
    """Fail loudly instead of hanging if the pipeline ever deadlocks."""
    for _ in range(limit):
        yield
    raise AssertionError(f"simulation exceeded {limit} cycles (deadlock?)")

def run_foc(dut, abc, angles, n, throttle=(0.2, 0.3), ready_rate=0.7, extra=None):
    captured = []
    run_simulation(dut, [
        stream_driver(dut.sink, [{"a": int(x), "b": int(y), "c": int(z)} for x, y, z in zip(*abc)],
            ["a", "b", "c"], seed=1, throttle=throttle[0]),
        stream_driver(dut.sink_angle, [{"angle": int(t)} for t in angles], ["angle"],
            seed=2, throttle=throttle[1]),
        stream_capture(dut.source, captured, n, ["a", "b", "c"], seed=3, ready_rate=ready_rate),
        watchdog(40*n + 400),
    ] + (extra or []))
    return tuple(column(captured, f, 16) for f in ("a", "b", "c"))

def balanced(theta, amp):
    return (np.round(amp*np.cos(theta)).astype(np.int64),
            np.round(amp*np.cos(theta - 2*np.pi/3)).astype(np.int64),
            np.round(amp*np.cos(theta + 2*np.pi/3)).astype(np.int64))

class TestFOC(unittest.TestCase):
    GAINS = dict(kp_d=int(0.8*ONE), ki_d=int(0.1*ONE), kp_q=int(1.2*ONE), ki_q=int(0.15*ONE))

    def build(self, setpoints=(0, 8000), limit=20000, **kwargs):
        dut = LiteDSPFOC(data_width=16, angle_width=AW, with_csr=False, **kwargs)
        dut.dq.setpoint_d.reset, dut.dq.setpoint_q.reset, dut.dq.limit.reset = (*setpoints, limit)
        for k, v in self.GAINS.items():
            getattr(dut.dq, k).reset = v
        return dut

    # verify-tier: model — the composite is the composition of the block models (Clarke, ROM
    # sin/cos, mixer, d/q PI, mixer, SVPWM), sample-aligned through the split/delay fan-out;
    # bit-exact with both sinks independently throttled (a deadlock would trip the watchdog).
    def test_bit_exact_under_backpressure(self):
        n    = 300
        prng = random.Random(5)
        abc  = tuple([prng.randint(-20000, 20000) for _ in range(n)] for _ in range(3))
        ang  = [prng.randint(-TURN//2, TURN//2 - 1) for _ in range(n)]
        for decoupling, latency in ((False, 9), (True, 10)):
            with self.subTest(decoupling=decoupling):
                dut = self.build(decoupling=decoupling)
                dut.speed.reset, dut.dq.l_pu.reset, dut.dq.psi_pu.reset = 12000, 5000, 20000
                got = run_foc(dut, abc, ang, n)
                ref = foc_model(*abc, ang, 0, 8000, limit=20000, decoupling=decoupling,
                    speed=12000, l_pu=5000, psi_pu=20000, **self.GAINS)
                for g, r in zip(got, ref):
                    self.assertTrue(np.array_equal(g, r))
                self.assertEqual(dut.latency, latency)

    # verify-tier: bound — open-loop bring-up: with mode = open loop and voltage_q = 0.5 pu the
    # duties are the SVPWM of a rotating vector of magnitude 0.5 (inverse Park of (0, 0.5)):
    # bit-exact vs the modulation models and, as a sanity check, the phase-a fundamental has
    # amplitude 0.5 pu within 1 % and leads the angle by 90 degrees within 1 degree.
    def test_open_loop_rotating_vector(self):
        n   = 1024
        ang = ((np.arange(n)*(TURN//64)) % TURN).astype(np.int64)
        ang = np.where(ang >= TURN//2, ang - TURN, ang)
        dut = self.build()
        dut.dq.open_loop.reset, dut.dq.voltage_q.reset = 1, int(0.5*FS)
        got = run_foc(dut, ([0]*n, [0]*n, [0]*n), ang, n, throttle=(0.0, 0.0), ready_rate=1.0)
        v_a, v_b = inverse_park_model([0]*n, [int(0.5*FS)]*n, ang)
        ref = svpwm_model(v_a, v_b, 1)
        for g, r in zip(got, ref):
            self.assertTrue(np.array_equal(g, r))
        # Fundamental of phase a: the zero-sequence injection is harmonic 3 only.
        k    = np.arange(n)
        wt   = 2*np.pi*ang/TURN
        A    = np.stack([np.cos(wt), np.sin(wt)], axis=1)
        coef = np.linalg.lstsq(A, got[0].astype(float), rcond=None)[0]
        amp, phase = np.hypot(*coef), np.degrees(np.arctan2(-coef[1], coef[0]))
        self.assertLess(abs(amp/FS - 0.5), 0.005)
        self.assertLess(abs(abs(phase) - 90.0), 1.0)

    # verify-tier: bound — closed loop on a per-unit RL current plant i' = i + Ts/L*(v - R*i)
    # (Ts/L = 0.2, R/L*Ts = 0.01) stepped in the test generator, one plant step per control
    # sample, rotor locked (ideal angle 0). With kp = 2 and ki/kp = 0.01 the PI zero cancels
    # the plant pole (0.99), leaving a first-order loop with pole 1 - Ts/L*kp = 0.6: i_q
    # reaches the 0.4 pu setpoint within 2 % in ln(0.02)/ln(0.6) = 7.7 samples with no
    # overshoot (measured: 8 samples, peak 0.400 at LITEDSP_SEED=0); i_d stays below 0.05 pu.
    # (The app-note example runs the full PMSM plant + PWM chain.)
    def test_closed_loop_plant_step(self):
        n, Ts_L, R_L = 120, 0.2, 0.05
        target = int(0.4*FS)
        dut = self.build(setpoints=(0, target), limit=FS)
        dut.dq.kp_d.reset = dut.dq.kp_q.reset = int(2.0*ONE)
        dut.dq.ki_d.reset = dut.dq.ki_q.reset = int(0.02*ONE)
        st  = {"d": 0.0, "q": 0.0, "theta": 0.0}
        log = {"d": [], "q": []}

        def loop():
            yield dut.source.ready.eq(1)
            for k in range(n):
                theta = st["theta"]
                i_ab  = (st["d"] + 1j*st["q"])*np.exp(1j*theta)
                al, be = i_ab.real*FS, i_ab.imag*FS
                ia, ib, ic = al, (-al + np.sqrt(3)*be)/2, (-al - np.sqrt(3)*be)/2   # Inverse Clarke.
                ang = int(round(theta/(2*np.pi)*TURN)) % TURN
                ang = ang - TURN if ang >= TURN//2 else ang
                yield dut.sink.a.eq(int(round(ia)))
                yield dut.sink.b.eq(int(round(ib)))
                yield dut.sink.c.eq(int(round(ic)))
                yield dut.sink.valid.eq(1)
                yield dut.sink_angle.angle.eq(ang)
                yield dut.sink_angle.valid.eq(1)
                yield
                while not ((yield dut.sink.ready) and (yield dut.sink_angle.ready)):
                    yield
                yield dut.sink.valid.eq(0)
                yield dut.sink_angle.valid.eq(0)
                while not (yield dut.source.valid):
                    yield
                da = (yield dut.source.a); db = (yield dut.source.b); dc = (yield dut.source.c)
                s = lambda v: (v - 65536 if v >= 32768 else v)/FS
                # Average-value inverter: phase voltages (pu of V_dc/2) = duties; Clarke -> dq.
                va = (2*s(da) - s(db) - s(dc))/3
                vb = (s(db) - s(dc))/np.sqrt(3)
                v_dq = (va + 1j*vb)*np.exp(-1j*theta)
                v_d, v_q = v_dq.real, v_dq.imag
                d, q = st["d"], st["q"]
                st["d"] = d + Ts_L*(v_d - R_L*d)
                st["q"] = q + Ts_L*(v_q - R_L*q)
                log["d"].append(st["d"]); log["q"].append(st["q"])
                yield

        run_simulation(dut, [loop(), watchdog(60*n)])
        iq = np.array(log["q"])
        err = np.abs(iq - 0.4)/0.4
        settled = int(np.nonzero(err > 0.02)[0][-1]) + 1 if np.any(err > 0.02) else 0
        self.assertLess(settled, 20, f"settled after {settled} samples")
        self.assertLess(iq.max(), 0.41, f"peak i_q {iq.max():.3f}")
        self.assertLess(np.max(np.abs(log["d"])), 0.05)

    def test_invalid(self):
        for kwargs in ({"anti_windup": "x"}, {"three_wire": "yes"}, {"lut_depth": 1000}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPFOC(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
