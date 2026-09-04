#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.motor.pi import LiteDSPPIController, LiteDSPDQController

from test.common import run_stream, stream_driver, stream_capture, column
from test.models import pi_controller_model, dq_controller_model

FS   = (1 << 15) - 1
ONE  = 1 << 12                                   # 1.0 in Q4.12.

def closed_loop(dut, plant, n, fields_in, fields_out, setup=None):
    """Run ``dut`` in a sample-by-sample loop with a Python plant.

    ``plant(k, u_prev)`` returns the measurement dict for sample k given the previous command
    (``None`` for k == 0); returns the list of commands (dicts) in order.
    """
    log = []

    def loop():
        if setup:
            for stmt in setup:
                yield stmt
        yield dut.source.ready.eq(1)
        u = None
        for k in range(n):
            y = plant(k, u)
            for f in fields_in:
                yield getattr(dut.sink, f).eq(int(y[f]))
            yield dut.sink.valid.eq(1)
            yield
            while not (yield dut.sink.ready):
                yield
            yield dut.sink.valid.eq(0)
            while not (yield dut.source.valid):
                yield
            u = {}
            for f in fields_out:
                u[f] = (yield getattr(dut.source, f))
            log.append(u)
            yield
    run_simulation(dut, loop())
    return log

def signed(v, width=16):
    return v - (1 << width) if v >= (1 << (width - 1)) else v

class TestPIController(unittest.TestCase):
    def run_pi(self, y, dut, throttle=0.2, ready_rate=0.7):
        cap = run_stream(dut, [{"data": int(v)} for v in y], len(y), ["data"], ["data"],
            sink_throttle=throttle, source_ready_rate=ready_rate)
        return column(cap, "data", 16)

    # verify-tier: model — a low limit (0.5 FS) with large gains exercises both clamps and the
    # anti-windup branch; the trajectory depends only on accepted samples (bit-exact under
    # randomized backpressure for every anti-windup mode).
    def test_bit_exact_under_backpressure(self):
        n    = 300
        prng = random.Random(1)
        y    = [prng.randint(-FS, FS) for _ in range(n)]
        sp, kp, ki, limit, ff = 6000, int(1.5*ONE), int(0.2*ONE), FS//2, -1500
        for mode in ("conditional", "clamp", "none"):
            with self.subTest(anti_windup=mode):
                dut = LiteDSPPIController(data_width=16, anti_windup=mode, with_csr=False)
                dut.setpoint.reset, dut.kp.reset, dut.ki.reset = sp, kp, ki
                dut.limit.reset, dut.feedforward.reset = limit, ff      # Signed reset: as int.
                got = self.run_pi(y, dut)
                ref = pi_controller_model(y, sp, kp, ki, limit, feedforward=ff, anti_windup=mode)
                self.assertTrue(np.array_equal(got, ref))
                self.assertEqual(dut.latency, 1)

    # verify-tier: model — setpoint on a second sink (join), both sinks throttled independently.
    def test_setpoint_stream_bit_exact(self):
        n    = 300
        prng = random.Random(2)
        y    = [prng.randint(-FS, FS) for _ in range(n)]
        sp   = [prng.randint(-FS, FS) for _ in range(n)]
        dut  = LiteDSPPIController(data_width=16, setpoint_stream=True, with_csr=False)
        dut.kp.reset, dut.ki.reset, dut.limit.reset = int(0.7*ONE), int(0.05*ONE), 20000
        captured = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": v} for v in y], ["data"], seed=3, throttle=0.2),
            stream_driver(dut.sink_ref, [{"data": v} for v in sp], ["data"], seed=4, throttle=0.3),
            stream_capture(dut.source, captured, n, ["data"], seed=5, ready_rate=0.7),
        ])
        ref = pi_controller_model(y, np.array(sp), int(0.7*ONE), int(0.05*ONE), 20000)
        self.assertTrue(np.array_equal(column(captured, "data", 16), ref))

    # verify-tier: bound — first-order plant y[k+1] = y[k] + a*(u[k] - y[k]) (a = 0.1, pole at
    # 0.9). With kp = 2.0 and ki = 0.2 the PI zero 1 - ki/kp = 0.9 cancels the plant pole, so
    # the closed loop is first order with pole 1 - a*kp = 0.8: 2 % settling in
    # ln(0.02)/ln(0.8) = 17.5 samples, no overshoot, zero steady-state error (integral
    # action). Measured at LITEDSP_SEED=0: settles in 18 samples, overshoot 0.0 %.
    def test_first_order_plant_step(self):
        n, a, target = 200, 0.1, 12000
        dut = LiteDSPPIController(data_width=16, with_csr=False)
        dut.setpoint.reset, dut.kp.reset, dut.ki.reset = target, 2*ONE, int(0.2*ONE)
        state = {"y": 0.0}
        ys = []

        def plant(k, u):
            if u is not None:
                state["y"] += a*(signed(u["data"]) - state["y"])
            ys.append(state["y"])
            return {"data": int(round(state["y"]))}

        closed_loop(dut, plant, n, ["data"], ["data"])
        ys = np.array(ys)
        err = np.abs(ys - target)/target
        settled = int(np.nonzero(err > 0.02)[0][-1]) + 1
        self.assertLess(settled, 30)
        self.assertLess(ys.max(), 1.02*target)
        self.assertLess(abs(ys[-20:].mean() - target), 0.005*target)

    # verify-tier: bound — wind-up scenario: setpoint at +FS with the plant stuck at 0 for
    # 200 samples (output clamped at +limit), then setpoint 0 with y = +2000 (e = -2000).
    # Recovery = samples until the output drops below limit/2, i.e. until the integrator
    # discharges to I_thr = (limit/2 + kp*|e|) << gain_frac at ki*|e| per sample:
    # conditional never integrated while clamped (recovery 0); clamp starts from
    # limit << gain_frac (bound derived below, ~75 samples); none starts from 200*ki*FS
    # (~5.4e8, no wrap at 2**29) and cannot recover within the 400-sample window.
    def test_anti_windup_modes(self):
        n_sat, n_rec, limit, e_rec = 200, 400, 8000, 2000
        kp, ki = int(0.5*ONE), int(0.02*ONE)
        n  = n_sat + n_rec
        sp = [FS]*n_sat + [0]*n_rec
        y  = [0]*n_sat + [e_rec]*n_rec
        recovery = {}
        for mode in ("conditional", "clamp", "none"):
            dut = LiteDSPPIController(data_width=16, setpoint_stream=True, anti_windup=mode,
                with_csr=False)
            dut.kp.reset, dut.ki.reset, dut.limit.reset = kp, ki, limit
            captured = []
            run_simulation(dut, [
                stream_driver(dut.sink, [{"data": v} for v in y], ["data"], seed=7),
                stream_driver(dut.sink_ref, [{"data": v} for v in sp], ["data"], seed=8),
                stream_capture(dut.source, captured, n, ["data"], seed=9),
            ])
            us = column(captured, "data", 16)
            self.assertTrue(np.array_equal(us, pi_controller_model(y, np.array(sp), kp, ki,
                limit, anti_windup=mode)))
            self.assertTrue(np.all(us[10:n_sat] == limit))                    # On the rail.
            below = np.nonzero(us[n_sat:] < limit//2)[0]
            recovery[mode] = int(below[0]) if len(below) else n_rec
        i_thr = (limit//2 + ((kp*e_rec) >> 12)) << 12
        bound = -(-((limit << 12) - i_thr)//(ki*e_rec)) + 2
        self.assertEqual(recovery["conditional"], 0)
        self.assertLessEqual(recovery["clamp"], bound)
        self.assertLess(recovery["clamp"], recovery["none"])
        self.assertEqual(recovery["none"], n_rec)

    def test_open_loop_and_clear(self):
        n, n_open = 300, 100
        dut = LiteDSPPIController(data_width=16, with_csr=False)
        dut.setpoint.reset, dut.kp.reset, dut.ki.reset = 5000, ONE, int(0.1*ONE)
        dut.limit.reset, dut.feedforward.reset = 3000, 7000     # ff beyond the limit: clamped.

        @passive
        def ctrl():
            # Open loop for the first n_open accepted samples, closed loop afterwards.
            yield dut.open_loop.eq(1)
            accepted = 0
            while accepted < n_open:
                yield
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    accepted += 1
            yield dut.open_loop.eq(0)
            while True:
                yield

        cap = run_stream(dut, [{"data": 0}]*n, n, ["data"], ["data"], sink_throttle=0.0,
            source_ready_rate=1.0, extra=[ctrl()])
        got = column(cap, "data", 16)
        self.assertTrue(np.all(got[:n_open] == 3000))          # Open loop: clamp(ff).
        ref = pi_controller_model([0]*n, 5000, ONE, int(0.1*ONE), 3000, feedforward=7000,
            open_loop=np.array([1]*n_open + [0]*(n - n_open)))
        self.assertTrue(np.array_equal(got, ref))

    def test_invalid(self):
        for kwargs in ({"anti_windup": "x"}, {"gain_frac": 16}, {"gain_frac": 0},
                       {"setpoint_stream": 1}, {"data_width": 2}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPPIController(with_csr=False, **kwargs)

class TestDQController(unittest.TestCase):
    # verify-tier: model — lock-stepped axes, with and without the decoupling stage.
    def test_bit_exact_under_backpressure(self):
        n    = 300
        prng = random.Random(6)
        i_d  = [prng.randint(-FS, FS) for _ in range(n)]
        i_q  = [prng.randint(-FS, FS) for _ in range(n)]
        gains = dict(kp_d=int(0.8*ONE), ki_d=int(0.1*ONE), kp_q=int(1.2*ONE), ki_q=int(0.15*ONE))
        for decoupling, latency in ((False, 1), (True, 2)):
            with self.subTest(decoupling=decoupling):
                dut = LiteDSPDQController(data_width=16, decoupling=decoupling, with_csr=False)
                dut.setpoint_d.reset, dut.setpoint_q.reset, dut.limit.reset = -2000, 9000, 20000
                for k, v in gains.items():
                    getattr(dut, k).reset = v
                dut.speed.reset, dut.l_pu.reset, dut.psi_pu.reset = 12000, 5000, 20000
                cap = run_stream(dut, [{"i": i_d[k], "q": i_q[k]} for k in range(n)], n,
                    ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
                rd, rq = dq_controller_model(i_d, i_q, -2000, 9000, limit=20000,
                    decoupling=decoupling, speed=12000, l_pu=5000, psi_pu=20000, **gains)
                self.assertTrue(np.array_equal(column(cap, "i", 16), rd))
                self.assertTrue(np.array_equal(column(cap, "q", 16), rq))
                self.assertEqual(dut.latency, latency)

    # verify-tier: bound — per-unit PMSM current plant with cross-coupling at w = 0.5 pu:
    # a q-current step disturbs i_d through +w*L*i_q; the decoupling feed-forward cancels it,
    # so the d-axis excursion must be at least 3x smaller than without (measured at
    # LITEDSP_SEED=0: 1470 vs 246 counts, ratio 6.0).
    def test_dq_plant_step_decoupling(self):
        n, Ts_L, R_L, w, L_pu, psi = 200, 0.2, 0.05, 0.5, 0.3, 0.6
        target_q = 12000
        excursions = {}
        for decoupling in (False, True):
            dut = LiteDSPDQController(data_width=16, decoupling=decoupling, with_csr=False)
            dut.setpoint_d.reset, dut.setpoint_q.reset = 0, target_q
            dut.kp_d.reset = dut.kp_q.reset = int(1.0*ONE)
            dut.ki_d.reset = dut.ki_q.reset = int(0.1*ONE)
            dut.speed.reset  = int(w*FS)
            dut.l_pu.reset   = int(L_pu*FS)
            dut.psi_pu.reset = int(psi*FS)
            st = {"d": 0.0, "q": 0.0}
            ds = []

            def plant(k, u, st=st, ds=ds):
                if u is not None:
                    v_d, v_q = signed(u["i"])/FS, signed(u["q"])/FS
                    d, q = st["d"], st["q"]
                    st["d"] = d + Ts_L*(v_d - R_L*d + w*L_pu*q)
                    st["q"] = q + Ts_L*(v_q - R_L*q - w*L_pu*d - w*psi)
                ds.append(st["d"])
                return {"i": int(round(st["d"]*FS)), "q": int(round(st["q"]*FS))}

            closed_loop(dut, plant, n, ["i", "q"], ["i", "q"])
            excursions[decoupling] = float(np.max(np.abs(ds)))*FS
        self.assertGreater(excursions[False], 3*excursions[True])

    def test_open_loop_passes_voltages(self):
        n   = 50
        dut = LiteDSPDQController(data_width=16, with_csr=False)
        dut.open_loop.reset, dut.voltage_d.reset, dut.voltage_q.reset = 1, 1234 & 0xFFFF, (
            -4321) & 0xFFFF
        cap = run_stream(dut, [{"i": 100, "q": -100}]*n, n, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        self.assertTrue(np.all(column(cap, "i", 16) == 1234))
        self.assertTrue(np.all(column(cap, "q", 16) == -4321))

    def test_invalid(self):
        with self.assertRaises(ValueError):
            LiteDSPDQController(decoupling="yes", with_csr=False)
        with self.assertRaises(ValueError):
            LiteDSPDQController(anti_windup="bad", with_csr=False)

if __name__ == "__main__":
    unittest.main()
