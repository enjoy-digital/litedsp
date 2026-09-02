# Motor control blocks

The `litedsp/motor/` family implements field-oriented control (FOC) of PMSM/BLDC machines on
the same stream contract as the RF blocks (`doc/interfaces.md`): every block is a
`LiteDSP`-prefixed `LiteXModule` with `valid`/`ready` streams, plain control signals mapped to
CSRs, a declared `latency`, a bit-exact NumPy golden model and Verilator co-simulation. This
page collects the conventions the family shares; the per-block datasheets are in
`doc/blocks/`, and [AN009](app_notes/an009_foc_pmsm.md) runs the whole loop on a motor model.

## Layouts and conventions

| Quantity | Layout | Convention |
|---|---|---|
| Three-phase currents / duties | `abc_layout` (`a`, `b`, `c`, signed) | Per-unit Q1.(N-1): `1.0` = base current `I_b` (currents) or `V_dc/2` (voltages, duties: `-1..+1` = 0..100 %) |
| Stationary αβ and rotating dq vectors | `iq_layout` (`i` = α or d, `q` = β or q) | The space vector `α + jβ` is a complex number, so the Park rotation *is* `LiteDSPMixer` (down = `a·conj(b)` = Park, up = inverse Park) |
| Electrical angle | `angle_layout` (`angle`, signed) | Full turn = `2**angle_width` (CORDIC/NCO convention, `π = 2**(angle_width-1)`); modular subtraction is the signed difference |
| Speed | Signals / CSR status | Angle units per control period (trackers, Q.frac) or per-unit of the base speed `ω_b` (controller decoupling input) |
| Loop gains | Signed Q4.12 (`gain_width=16`, `gain_frac=12`) | `1.0 = 4096`; the same scale for the per-unit plant constants `R`, `L`, `ψ` |

Per-unit scaling (`I_b`, `V_b = V_dc/2`, `ω_b`, control period `Ts`) is defined once by the
host: the PI gains of a current loop are `kp = ω_c·L/(V_b/I_b)`, `ki = kp·R/L·Ts`; the
decoupling constants are `L_pu = ω_b·L·I_b/V_b` and `ψ_pu = ω_b·ψ/V_b`; the observer gains are
`g_v = ω_b·Ts/L_pu` and `g_r = R_pu·g_v`.

## The loop is paced by the PWM

`LiteDSPPWM` accepts exactly one duty sample per carrier period (at the valley) and applies it
at the next valley (double buffering). Feeding it from `LiteDSPFOC` therefore runs the whole
chain at the PWM rate through backpressure alone: no sample counters, no clock-enable tree.
Its `trigger` output marks the ADC sample point (carrier value + slope, e.g. the valley for
low-side shunt sampling); a `LiteDSPQuadratureDecoder`/`LiteDSPHallDecoder` emits its angle
on the same strobe, and the `LiteDSPSigmaDeltaFilter` produces its currents at `1/rate` of the
modulator bit rate (set the rate so that one sample lands per period).

```
                      +----------- LiteDSPFOC ---------------------------------+
  i_abc  (abc) ------>| Clarke -> Park --> DQController --> InversePark -> SVPWM |---> duties ---> LiteDSPPWM ---> gates
  angle (angle) ----->|          ^  sin/cos (split + delay)  ^                   |      (abc)      |  trigger, fault
                      +----------------------------------------------------------+                 v
                                                                                            ADC / sigma-delta sample point
```

`LiteDSPFOC` keeps the Park and inverse-Park rotations sample-aligned with an atomic fan-out
of the sin/cos sample and a delay matched to the Park + controller latency (the same
delay-balancing rule the flow tool applies to reconvergent branches). Its control surface is
the d/q controller's CSRs (`dq_setpoint_*`, `dq_kp_*`, `dq_ki_*`, `dq_limit`, `dq_voltage_*`,
`dq_control.open_loop` for open-loop bring-up) and the modulator's `svpwm_control.injection`.

## Bring-up sequence

1. **Open loop**: `dq_control.open_loop = 1`, `dq_voltage_q` = a small vector, the angle from
   `LiteDSPAngleRamp` (constant electrical frequency): the motor rotates in V/f mode. Check the
   phase currents in `LiteDSPCapture` and the gate signals.
2. **Current loop**: with the rotor locked (or the angle from the sensor), `open_loop = 0`,
   step `dq_setpoint_q`; tune `kp`/`ki` on the captured `i_q` (the pole-cancelling design
   `ki/kp = R/L·Ts` gives a first-order response).
3. **Sensor alignment**: `angle_offset` of the encoder/Hall decoder so that `i_d ≈ 0` at
   steady state (or the resolver's `phase_offset` for maximum `raw_mag`).
4. **Speed loop** (host or a CSR-driven `LiteDSPPIController` + `LiteDSPSlewLimiter` on the
   reference), then the sensorless switch-over: `LiteDSPSMObserver` → `LiteDSPAngleTracker`
   replaces the sensor angle above the minimum observable speed (`k_sm` ≈ half the back-EMF).

## Protection

`LiteDSPOvercurrentTrip` (window comparator on the sampled currents) and the fast path of
`LiteDSPSigmaDeltaFilter` (a short sinc³ decimator per phase, independent of the control-path
rate) latch a fault within a few modulator bits; wire their `fault`/`overcurrent` to the PWM's
`fault` input, which switches all six gate signals off within one clock and latches until
`fault_clear`. Every latch has an `EventManager` IRQ (`with_irq=True`).

## Verification

Every block has a bit-exact golden model in `test/models.py` (the FOC model is the composition
of the block models) exercised under randomized backpressure, and every stream-shaped block is
Verilator co-simulated (`sim/cosim_specs.py`); the pin-level blocks (PWM, encoders, resolver
excitation) have cycle-exact register models. Functional bounds (settling, overshoot, angle
error, lag) are derived in the tests from the gains and pinned with the seed-0 measurement.
