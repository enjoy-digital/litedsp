#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""PMSM field-oriented control (AN009): closed loop on a per-unit motor model.

The RTL current controller and PWM generator drive a NumPy PMSM/inverter plant stepped once per
PWM period (the PWM's one-sample-per-period acceptance paces the loop, exactly as on hardware):

    plant currents (abc) --> FOC (Clarke -> Park -> d/q PI -> inverse Park -> SVPWM) --> PWM
            ^                         ^ rotor angle                                     |
            |                         |                                                 v
            `-- PMSM dq model <------ ideal angle | QuadratureDecoder(A/B pins) | SMO -> tracker

Three variants share the plant and the gates: an ideal angle, the RTL quadrature-encoder
decoder fed from emulated A/B pins, and sensorless operation (sliding-mode observer + angle
tracker after an open-loop V/f start). A Python speed loop (the "firmware") writes the q-axis
current setpoint through the controller's registers.

Documented simplifications (doc/app_notes/an009_foc_pmsm.md): average-value inverter (duties
are phase voltages, no switching ripple), Euler-stepped per-unit plant, no field weakening.

Run: python3 examples/foc_pmsm.py [--plot-dir DIR]
"""

import os
import sys
import argparse

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common           import angle_layout
from litedsp.motor.foc        import LiteDSPFOC
from litedsp.motor.pwm        import LiteDSPPWM
from litedsp.motor.encoder    import LiteDSPQuadratureDecoder
from litedsp.motor.observer   import LiteDSPSMObserver, LiteDSPAngleTracker
from litedsp.motor.transforms import LiteDSPAngleRamp
from litedsp.stream.route     import LiteDSPChannelMux

# Parameters ---------------------------------------------------------------------------------------
#
# Per-unit machine (base: rated current I_b, V_b = V_dc/2, base speed w_b): R = 0.05, L = 0.3
# (w_b*L/Z_b), psi = 0.6 (w_b*psi/V_b); w_b*Ts = 0.05 rad of electrical angle per PWM period at
# base speed. Mechanical: J = 2.0 (per-unit inertia), B = 0.02, load torque 0.1.
FS       = (1 << 15) - 1
ONE      = 1 << 12                     # 1.0 in the Q4.12 gain format.
TURN     = 1 << 16
R_PU, L_PU, PSI_PU = 0.05, 0.3, 0.6
WB_TS    = 0.05
J_PU, B_PU, T_LOAD = 2.0, 0.02, 0.1
PERIOD   = 24                          # PWM half period in cycles (48 cycles per control period).
CPR, POLE_PAIRS = 1024, 2              # Encoder counts per mechanical turn, motor pole pairs.

# Current loop: pole-cancelling PI (ki/kp = R/L*w_b*Ts), closed-loop pole 1 - w_b*Ts/L*kp = 0.75.
KP_I, KI_I = 1.5, 1.5*R_PU*WB_TS/L_PU
# Speed loop (Python firmware, per period): PI on w_pu -> i_q setpoint with conditional
# anti-windup, slew-limited reference (loop gain per period KP_W*psi*w_b*Ts/J = 0.12).
KP_W, KI_W, IQ_MAX, W_SLEW = 8.0, 0.2, 0.8, 0.02
W_TARGET = 0.5
# Sensorless: the observer angle lags the rotor by a constant at the operating point (back-EMF
# filter phase, partly compensated by the current model): calibrated once and added back.
SMO_LAG_DEG = 14.0
CLOSED_AT   = {"ideal": 0, "encoder": 0, "sensorless": 120}   # First closed-loop period.
ID_MAX      = {"ideal": 0.08, "encoder": 0.08, "sensorless": 0.15}   # |i_d| gate once settled
                                                                     # (observer chatter).

# Top-level: FOC + PWM (+ sensor variant) ----------------------------------------------------------

class FOCDrive(LiteXModule):
    def __init__(self, sensor="ideal"):
        self.sensor = sensor
        self.foc = LiteDSPFOC(data_width=16, angle_width=16, with_csr=False)
        self.pwm = LiteDSPPWM(data_width=16, period_width=8, dead_time_width=4, with_csr=False)
        self.pwm.period.reset = PERIOD
        self.pwm.enable.reset = 1
        self.comb += self.foc.source.connect(self.pwm.sink)
        if sensor == "encoder":
            self.enc = LiteDSPQuadratureDecoder(angle_width=16, position_width=12, filter_length=1,
                with_csr=False)
            self.enc.counts_per_rev.reset = CPR
            self.enc.pole_pairs.reset     = POLE_PAIRS
            self.enc.angle_scale.reset    = (1 << 32)//CPR
            self.comb += self.enc.source.connect(self.foc.sink_angle)
        elif sensor == "sensorless":
            self.smo     = LiteDSPSMObserver(data_width=16, angle_width=16, with_csr=False)
            self.tracker = LiteDSPAngleTracker(angle_width=16, kp_shift=3, ki_shift=8,
                                               with_csr=False)
            self.ramp    = LiteDSPAngleRamp(angle_width=16, with_csr=False)
            self.mux     = LiteDSPChannelMux(n=2, layout=angle_layout(16), with_csr=False)
            self.smo.g_v.reset  = int(round(WB_TS/L_PU*ONE))
            self.smo.g_r.reset  = int(round(R_PU*WB_TS/L_PU*ONE))
            self.smo.k_sm.reset = int(0.35*W_TARGET*FS)
            self.smo.lpf_shift.reset = 4
            self.comb += [
                self.smo.source.connect(self.tracker.sink),
                self.ramp.source.connect(self.mux.sinks[0]),
                self.tracker.source.connect(self.mux.sinks[1]),
                self.mux.source.connect(self.foc.sink_angle),
            ]

# Plant --------------------------------------------------------------------------------------------

class PMSM:
    """Per-unit PMSM in the rotor frame + average-value inverter, stepped once per PWM period."""
    def __init__(self):
        self.i_d = self.i_q = 0.0
        self.w = self.theta = 0.0                       # Electrical speed (pu) and angle (rad).
        self.v_d = self.v_q = 0.0

    def apply_duties(self, da, db, dc):
        va = (2*da - db - dc)/3                         # Clarke of the phase voltages (pu).
        vb = (db - dc)/np.sqrt(3)
        v  = (va + 1j*vb)*np.exp(-1j*self.theta)        # Park.
        self.v_d, self.v_q = v.real, v.imag

    def step(self, substeps=4):
        h = WB_TS/substeps
        for _ in range(substeps):
            d, q, w = self.i_d, self.i_q, self.w
            self.i_d = d + h/L_PU*(self.v_d - R_PU*d + w*L_PU*q)
            self.i_q = q + h/L_PU*(self.v_q - R_PU*q - w*L_PU*d - w*PSI_PU)
            self.w   = w + h/J_PU*(PSI_PU*self.i_q - T_LOAD - B_PU*w)
            self.theta = (self.theta + self.w*h) % (2*np.pi)

    def currents_abc(self):
        i  = (self.i_d + 1j*self.i_q)*np.exp(1j*self.theta)
        al, be = i.real, i.imag
        return al, (-al + np.sqrt(3)*be)/2, (-al - np.sqrt(3)*be)/2

    def alphabeta(self):
        i = (self.i_d + 1j*self.i_q)*np.exp(1j*self.theta)
        v = (self.v_d + 1j*self.v_q)*np.exp(1j*self.theta)
        return i.real, i.imag, v.real, v.imag

def q15(x):
    return int(np.clip(round(x*FS), -FS, FS))

def angle_word(theta):
    a = int(round(theta/(2*np.pi)*TURN)) % TURN
    return a - TURN if a >= TURN//2 else a

# Simulation ---------------------------------------------------------------------------------------

def simulate(sensor, n_periods, log):
    top   = FOCDrive(sensor)
    plant = PMSM()
    state = {"iq_ref": 0.0, "w_ref": 0.0, "w_int": 0.0, "duties": (0.0, 0.0, 0.0), "period": 0,
             "mode": "open" if sensor == "sensorless" else "closed"}

    @passive
    def duty_watch():
        # Duties accepted by the PWM at each valley become the applied voltages.
        while True:
            if (yield top.pwm.sink.valid) and (yield top.pwm.sink.ready):
                s = lambda v: (v - 65536 if v >= 32768 else v)/FS
                state["duties"] = (s((yield top.pwm.sink.a)), s((yield top.pwm.sink.b)),
                                   s((yield top.pwm.sink.c)))
            yield

    @passive
    def encoder_pins():
        # Emulated incremental encoder: the shaft angle advances linearly every clock at the
        # plant speed (resynchronized to the plant at each period), A/B follow the 4x count.
        gray  = [0b00, 0b01, 0b11, 0b10]
        theta = 0.0
        last  = None
        while True:
            if state["period"] != last:
                theta, last = plant.theta, state["period"]
            theta += plant.w*WB_TS/(2*PERIOD)
            count = int((theta/POLE_PAIRS)/(2*np.pi)*CPR) % 4
            yield top.enc.a.eq(gray[count] & 1)
            yield top.enc.b.eq(gray[count] >> 1)
            yield

    def firmware():
        # Speed loop at the period rate: slew-limited reference, PI -> i_q setpoint.
        w_ref = min(state["w_ref"] + W_SLEW, W_TARGET)
        e     = w_ref - plant.w
        u     = KP_W*e + state["w_int"]
        if not (abs(u) > IQ_MAX and np.sign(e) == np.sign(u)):      # Conditional anti-windup.
            state["w_int"] = float(np.clip(state["w_int"] + KI_W*e, -IQ_MAX, IQ_MAX))
        iq_ref = float(np.clip(KP_W*e + state["w_int"], -IQ_MAX, IQ_MAX))
        state["w_ref"], state["iq_ref"] = w_ref, iq_ref
        return iq_ref

    def control():
        foc, pwm = top.foc, top.pwm
        yield foc.dq.kp_d.eq(int(KP_I*ONE)); yield foc.dq.kp_q.eq(int(KP_I*ONE))
        yield foc.dq.ki_d.eq(int(KI_I*ONE)); yield foc.dq.ki_q.eq(int(KI_I*ONE))
        yield foc.dq.limit.eq(FS)
        if sensor == "sensorless":
            yield foc.dq.open_loop.eq(1)
            yield foc.dq.voltage_q.eq(q15(0.25))       # V/f start: 0.25 pu vector.
            yield top.ramp.phase_inc.eq(int(0.25*WB_TS/(2*np.pi)*(1 << 32)))   # 0.25 pu speed.
            yield top.mux.sel.eq(0)
        yield pwm.trigger_count.eq(0)
        for k in range(n_periods):
            # Wait for the carrier valley (ADC sample point), then apply the accepted duties and
            # step the plant over the period that just started.
            while not (yield pwm.trigger):
                yield
            plant.apply_duties(*state["duties"])
            plant.step()
            state["period"] = k + 1
            # Firmware: sensorless start-up sequence, then the speed loop.
            if sensor == "sensorless" and state["mode"] == "open" and k == 120:
                # Switch-over: observer angle (with the calibrated operating-point lag
                # compensation, see the app note) replaces the ramp, current loops close.
                yield top.tracker.angle_offset.eq(int(round(SMO_LAG_DEG/360*TURN)))
                yield foc.dq.open_loop.eq(0)
                yield top.mux.sel.eq(1)
                state["mode"] = "closed"
                state["w_ref"] = plant.w
            if state["mode"] == "closed":
                iq_ref = firmware()
                yield foc.dq.setpoint_q.eq(q15(iq_ref))
            # Measurements for this period: phase currents (+ angle / alpha-beta for the sensor).
            ia, ib, ic = plant.currents_abc()
            yield foc.sink.a.eq(q15(ia)); yield foc.sink.b.eq(q15(ib)); yield foc.sink.c.eq(q15(ic))
            yield foc.sink.valid.eq(1)
            if sensor == "ideal":
                yield foc.sink_angle.angle.eq(angle_word(plant.theta))
                yield foc.sink_angle.valid.eq(1)
            elif sensor == "encoder":
                yield top.enc.sample.eq(1)
            else:
                i_a, i_b, v_a, v_b = plant.alphabeta()
                yield top.smo.sink_i.i.eq(q15(i_a)); yield top.smo.sink_i.q.eq(q15(i_b))
                yield top.smo.sink_v.i.eq(q15(v_a)); yield top.smo.sink_v.q.eq(q15(v_b))
                yield top.smo.sink_i.valid.eq(1); yield top.smo.sink_v.valid.eq(1)
            yield
            if sensor == "encoder":
                yield top.enc.sample.eq(0)
            if sensor == "sensorless":
                yield top.smo.sink_i.valid.eq(0); yield top.smo.sink_v.valid.eq(0)
            while not (yield foc.sink.ready):
                yield
            yield foc.sink.valid.eq(0)
            yield foc.sink_angle.valid.eq(0)
            # Estimated angle as seen by the FOC (for the error plots).
            est = (yield foc.sink_angle.angle) if sensor == "ideal" else \
                  ((yield top.enc.source.angle) if sensor == "encoder"
                    else (yield top.mux.source.angle))
            est = est - TURN if est >= TURN//2 else est
            log["i_d"].append(plant.i_d); log["i_q"].append(plant.i_q); log["w"].append(plant.w)
            log["iq_ref"].append(state["iq_ref"]); log["w_ref"].append(state["w_ref"])
            log["theta"].append(plant.theta); log["est"].append(est/TURN*2*np.pi)
            log["duties"].append(state["duties"])
            yield

    gens = [control(), duty_watch()]
    if sensor == "encoder":
        gens.append(encoder_pins())
    run_simulation(top, gens)

def angle_error_deg(log, start):
    err = (np.array(log["est"][start:]) - np.array(log["theta"][start:])
                                                                + np.pi) % (2*np.pi) - np.pi
    return np.degrees(err)

# Plots --------------------------------------------------------------------------------------------

def save_plots(plot_dir, logs):
    try:
        import matplotlib
    except ImportError:
        print("  (matplotlib not available: skipping plots)")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(plot_dir, exist_ok=True)
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    for sensor, log in logs.items():
        k = np.arange(len(log["w"]))
        axes[0].plot(k, log["i_q"], label=f"i_q ({sensor})")
        axes[1].plot(k, log["w"],   label=f"w ({sensor})")
    axes[0].plot(k, logs["ideal"]["iq_ref"], "k--", label="i_q setpoint")
    axes[1].plot(k, logs["ideal"]["w_ref"],  "k--", label="w reference")
    axes[0].set_ylabel("i_q (pu)"); axes[1].set_ylabel("speed (pu)")
    for sensor in ("encoder", "sensorless"):
        axes[2].plot(np.arange(len(logs[sensor]["w"])), angle_error_deg(logs[sensor], 0),
            label=f"angle error ({sensor})")
    axes[2].set_ylabel("deg el."); axes[2].set_xlabel("PWM period")
    for ax in axes:
        ax.grid(True); ax.legend(loc="best", fontsize=8)
    fig.suptitle("AN009: PMSM field-oriented control (RTL FOC + PWM on a per-unit plant)")
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an009_foc.png"))
    print(f"  plots -> {plot_dir}/an009_foc.png")

# Main ---------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="AN009 PMSM field-oriented control.")
    parser.add_argument("--plot-dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
        "..", "doc", "app_notes", "img"))
    parser.add_argument("--periods", type=int, default=320)
    args = parser.parse_args()

    logs = {}
    for sensor in ("ideal", "encoder", "sensorless"):
        log = {k: [] for k in ("i_d", "i_q", "w", "iq_ref", "w_ref", "theta", "est", "duties")}
        simulate(sensor, args.periods, log)
        logs[sensor] = log
        w, iq, i_d = (np.array(log[k]) for k in ("w", "i_q", "i_d"))
        # Speed settling: within 2 % of the target from some period on.
        late = np.nonzero(np.abs(w - W_TARGET) > 0.02*W_TARGET)[0]
        settle = int(late[-1]) + 1 if len(late) else 0
        k0 = max(CLOSED_AT[sensor] + 40, settle)
        print(f"[{sensor:10s}] speed {w[-1]:.3f} pu (target {W_TARGET}), settled after {settle} "
              f"periods, |i_d| max {np.max(np.abs(i_d[k0:])):.3f} pu (settled), "
              f"i_q peak {iq.max():.3f} pu")
        if sensor != "ideal":
            err = angle_error_deg(log, settle)
            print(f"             angle error after settling: mean {err.mean():+.1f}, "
                  f"RMS {np.sqrt(np.mean((err - err.mean())**2)):.1f} deg el.")

    # Gates: the golden properties of the app note.
    for sensor, log in logs.items():
        w, i_d = np.array(log["w"]), np.array(log["i_d"])
        late = np.nonzero(np.abs(w - W_TARGET) > 0.02*W_TARGET)[0]
        settle = int(late[-1]) + 1 if len(late) else 0
        assert settle < args.periods - 40, f"{sensor}: speed did not settle ({settle})"
        k0 = max(CLOSED_AT[sensor] + 40, settle)
        assert np.max(np.abs(i_d[k0:])) < ID_MAX[sensor], \
            f"{sensor}: |i_d| exceeds {ID_MAX[sensor]} pu once settled"
    err = angle_error_deg(logs["encoder"], 40)
    assert np.sqrt(np.mean(err**2)) < 3.0, "encoder: angle error RMS >= 3 deg"
    err = angle_error_deg(logs["sensorless"], 200)
    assert np.sqrt(np.mean((err - err.mean())**2)) < 10.0, "sensorless: angle error RMS >= 10 deg"
    # The current loop: the first i_q step of the ideal variant.
    iq, ref = np.array(logs["ideal"]["i_q"]), np.array(logs["ideal"]["iq_ref"])
    assert iq.max() < 1.1*ref.max() + 0.02, "i_q overshoot > 10 %"
    print("  PASS: speed settles within 2 % for ideal / encoder / sensorless sensing, |i_d| < 0.08 "
          "pu"
          " (0.15 sensorless) once settled, encoder angle RMS < 3 deg, sensorless angle RMS < 10 "
          "deg")
    save_plots(args.plot_dir, logs)

if __name__ == "__main__":
    main()
