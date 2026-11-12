# Motor control blocks {#motor}

The `litedsp/motor/` family implements field-oriented control (FOC) of PMSM and BLDC machines on
the stream contract of the RF blocks. This chapter gives the conventions the family shares, the
blocks by stage, the FOC composite and the PWM-paced loop, then the bring-up, the protection, the
host side and the AN009 application note.

It assumes the concepts of [Motor control primer](#motor-primer). Every block follows
[Block contract](#architecture): `valid`/`ready` streams, plain control signals mapped to
registers by `with_csr=True`, a declared `latency` and a bit-exact NumPy golden model.

## At a glance {#mot-glance}

| Stage | Blocks | Files (`motor/`) |
| -------------- | -------------------------------------------------------- | ------------------------------ |
| Transforms | `LiteDSPClarke`, `LiteDSPInverseClarke`, `LiteDSPSinCos`, `LiteDSPPark`, `LiteDSPInversePark`, `LiteDSPAngleRamp` | `transforms.py` |
| Regulation | `LiteDSPPIController`, `LiteDSPDQController`, `LiteDSPSlewLimiter` | `pi.py`, `limiter.py` |
| Modulation | `LiteDSPSVPWM`, `LiteDSPPWM` | `svpwm.py`, `pwm.py` |
| Sensing | `LiteDSPSigmaDeltaFilter`, `LiteDSPOvercurrentTrip` | `sense.py` |
| Position | `LiteDSPQuadratureDecoder`, `LiteDSPHallDecoder`, `LiteDSPResolverDigital`, `LiteDSPAngleTracker`, `LiteDSPSMObserver` | `encoder.py`, `resolver.py`, `observer.py` |
| Composite | `LiteDSPFOC` | `foc.py` |

The family has 19 registry entries, one per class. Each has a datasheet in the online catalogue
([block index](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md), section
Motor Control), and its registers are listed in [Motor control](#reg-motor) of the register
appendix. The development status is in the [status table](#intro-status).

## Layouts and conventions {#mot-conventions}

The family adds two payload layouts and reuses the complex one. The table below gives the
quantity each layout carries and the convention of its values.

| Quantity | Layout | Convention |
|-------------------------------|--------------------|------------------------------------------------|
| Phase currents, phase duties | `abc_layout` | Signed per-unit Q1.(N-1): 1.0 is `I_b` for currents, `V_dc/2` for voltages; duty -1 to +1 is 0 to 100 % |
| Stationary and rotating vectors | `iq_layout` | `i` is `α` or `d`, `q` is `β` or `q`; the Park rotation is the complex mixer |
| Electrical angle | `angle_layout` | Signed; a full turn is `2**angle_width`, `π` is `2**(angle_width-1)` |
| Speed | Signals, registers | Angle units per control period (trackers), or per-unit of `ω_b` (decoupling input) |
| Loop gains | Signed Q4.12 | `kp`, `ki` and the observer gains `g_v`, `g_r`: `gain_width=16`, `gain_frac=12`, 1.0 is 4096 |
| Plant constants | Signed Q1.(N-1) | `l_pu` and `psi_pu` of the decoupling feed-forward, like the samples |

The modular subtraction of two angles is their signed difference, so an angle error needs no
wrap-around logic. The control period `Ts` is one PWM period throughout the family.

The host defines the per-unit bases once: `I_b`, `V_b = V_dc/2`, `ω_b` and `Ts`
([Per-unit scaling](#mpri-per-unit)). The block constants then follow from these formulas, with
`R`, `L` and `ψ` in physical units and `Ts` in seconds.

| Constant | Formula | Used by |
|-------------------|------------------------------------|------------------------------------|
| Current-loop `kp` | `ω_c·L/(V_b/I_b)` | `LiteDSPDQController` |
| Current-loop `ki` | `kp·R/L·Ts` | `LiteDSPDQController` |
| `L_pu` | `ω_b·L·I_b/V_b` | Decoupling feed-forward |
| `ψ_pu` | `ω_b·ψ/V_b` | Decoupling feed-forward |
| `g_v` | `ω_b·Ts/L_pu` | `LiteDSPSMObserver` |
| `g_r` | `R_pu·g_v` | `LiteDSPSMObserver` |

## Transforms {#mot-transforms}

The Clarke transform, `LiteDSPClarke`, takes an `abc_layout` sample and returns `α`/`β` on
`iq_layout`, with Q1.15 constants and one rounding and saturation per output. Its `three_wire`
option uses phases `a` and `b` only and saves a multiplier. The latency is one cycle.

The inverse Clarke transform, `LiteDSPInverseClarke`, saturates any vector above 1.0 per-unit.
In the space-vector linear range a phase voltage reaches 1.1547 per-unit, so the modulator keeps
its own, wider inverse Clarke instead.

The sin/cos block, `LiteDSPSinCos`, turns an angle stream into a unit vector (`i` is the cosine,
`q` the sine). Its default `method="rom"` reads the quarter-wave table of the NCO in one cycle,
without a multiplier. Its `method="cordic"` option rotates a full-scale vector instead, in
`stages + 3` cycles, with the full angle resolution.

The Park and inverse Park transforms, `LiteDSPPark` and `LiteDSPInversePark`, combine a sin/cos
block with the complex mixer in down or up mode. Both sinks, the vector and the angle, are
consumed together. The data path has a latency of two cycles; the angle path adds the sin/cos
latency.

The angle ramp, `LiteDSPAngleRamp`, is a phase accumulator that emits an angle stream. It drives
the open-loop bring-up and the sensorless start. For an electrical frequency `f_e` at a control
rate `f_ctrl`, the host sets `phase_inc = f_e/f_ctrl·2**phase_bits`.

## Regulators {#mot-regulators}

The PI regulator, `LiteDSPPIController`, computes `u = clamp(kp·e + integral + feedforward,
±limit)` for each accepted measurement. The output uses the integrator before its update, as
synchronous hardware does. Its latency is one cycle.

Its controls are the signed gains `kp` and `ki` (Q4.12 by default, `ki` per sample), a positive
output `limit` (reset: full scale), a `feedforward` term (the command in open loop), `open_loop`
(output is `feedforward`, integrator held at zero), `clear` and the sticky `saturated` flag.

The `anti_windup` parameter selects the integrator behaviour ([PI regulators and
anti-windup](#mpri-pi)). The default `"conditional"` stops integrating while the output is
clamped in the direction of the error. The `"clamp"` option only bounds the integrator to the
limit, and `"none"` lets it wrap. With `setpoint_stream=True`, the setpoint arrives on a second
stream, `sink_ref`, instead of a control.

The d/q controller, `LiteDSPDQController`, runs two PI regulators in lock step on the measured
`(i_d, i_q)` vector and outputs the `(v_d, v_q)` command. Each axis has its own setpoint and
gains; the limit is shared. In open loop it forwards the `voltage_d` and `voltage_q` bring-up
vector.

With `decoupling=True`, the d/q controller adds the cross-coupling feed-forward from a per-unit
`speed` input and the `l_pu` and `psi_pu` constants: `ff_d = -ω·L·i_q` and `ff_q = ω·(L·i_d +
ψ)`. That costs one more registered stage: the latency becomes two cycles instead of one.

The slew limiter, `LiteDSPSlewLimiter`, follows its input by at most `rate` per accepted sample.
A setpoint step of size `D` becomes a ramp of `ceil(D/rate)` samples with no overshoot. It uses
no multiplier and has a `bypass` control.

## Modulation and PWM {#mot-pwm}

The modulator, `LiteDSPSVPWM`, turns an `α`/`β` voltage command into three signed duties. It
computes the inverse Clarke transform two bits wider than the samples, then adds the min/max
zero sequence when its runtime `injection` control is set ([Modulation](#mpri-svpwm)). The
duties are saturated to ±1.0; the latency is three cycles.

The PWM generator, `LiteDSPPWM`, is a stream sink with six gate outputs, `pwm_h` and `pwm_l`. A
triangular carrier counts from 0 to `period` and back, so a PWM period lasts `2·period` cycles.
The table below lists its controls.

| Register | Meaning |
|------------------|----------------------------------------------------------------------|
| `period` | Half PWM period in cycles, the carrier peak (reset 1000) |
| `dead_time` | Cycles with both outputs low at every gate edge |
| `control` | `enable`, `fault_clear`, `missed_clear` |
| `trigger` | Carrier value and slope at which the ADC trigger pulses |
| `status` | `fault_latched`, `missed` |
| `count` | Carrier counter |

The sink accepts one duty sample per period, on the carrier valley. The PWM converts it to a
compare value `cmp = round(period·(duty + 1)/2)` with one time-shared multiplier and applies it at
the next valley. This double buffering is glitch-free and costs one period of latency.

If no sample arrives in a period, the PWM holds the previous duties and sets the sticky `missed`
flag (while the outputs are enabled). The high-side output is high while the carrier is below the
compare value, which centres the pulse on the valley; the low-side output is its complement, with
the dead time inserted on every edge.

The `trigger` output pulses when the carrier passes the programmed value on the programmed slope.
Direction 1 with the count set to `period` is the carrier peak, the sample point of low-side
shunts ([sample point](#mpri-pwm)); direction 0 near the valley suits high-side or in-line
sensing. The block docstring and `PWMDriver.set_trigger()` default to direction 0 and call it the
low-side sample point, which it is not; fix pending (PR #16, [Known issues](#intro-known-issues)). With
`with_irq=True`, the PWM adds a `fault` event and a `period` event that fires every valley, for a
loop run by a CPU.

## Current sensing and over-current trip {#mot-sensing}

The sigma-delta current sense, `LiteDSPSigmaDeltaFilter`, takes the modulator bitstreams of one
or three phases on `sinks` and consumes them in lock step. A runtime-rate bitstream decimator per
phase (`rate` and `shift` registers, reset from `decimation`) produces the currents at `1/rate`
of the bit rate.

Each phase also feeds a short sinc filter of fixed `fast_decimation`. Its output is compared with
`threshold`: an over-current sets the per-phase sticky `overcurrent` bits within
`fast_decimation` bits, whatever the control-path rate. The `n_stages` parameter sets the sinc
order of both paths, three by default.

The other parameters are `n_channels` (1 or 3 phases, 3 by default) and `r_max`, the largest
runtime rate of the control path (256).

The over-current trip, `LiteDSPOvercurrentTrip`, is a window comparator on a three-phase stream.
It passes the samples through with no latency. Any accepted sample above `threshold` in
magnitude sets the sticky `fault`, records which phase tripped and increments `count`.

**Protection.** Wire the trip's `fault` and the OR of the current sense's `overcurrent` bits to
the `fault` input of the PWM. The PWM switches all six gate signals off two clock cycles later
(the fault is latched, then the registered gate outputs fall) and holds `fault_latched` until the
host pulses `fault_clear`. Every latch has an event with `with_irq=True`: `ev.fault` on the PWM
and the trip, `ev.overcurrent` on the current sense. The docstrings of the PWM and of the trip
still say "within one cycle" (fix pending, PR #16, [Known issues](#intro-known-issues)).

## Position and speed {#mot-position}

The quadrature decoder, `LiteDSPQuadratureDecoder`, synchronizes and glitch-filters the A and B
pins, then decodes them at 4x resolution. An illegal transition sets the sticky `error`. The
index pulse, when enabled, zeroes the position and sets `index_seen`.

The electrical angle comes from an electrical position that advances by `pole_pairs` per count,
modulo `counts_per_rev`. A reciprocal multiply scales it: `angle = epos·angle_scale >> scale_frac
+ angle_offset`, with `angle_scale = round(2**(angle_width + scale_frac)/counts_per_rev)`. The
result is exact for power-of-two counts and within one LSB otherwise.

The decoder's `speed` is the signed count over the last `window` cycles. The angle stream is
emitted on the `sample` strobe, latest value wins, with a sticky `overrun` flag. Wiring the PWM
trigger to that strobe delivers the angle together with the currents.

The Hall decoder, `LiteDSPHallDecoder`, maps the three sensor bits to one of six sectors and emits
the sector centre plus `angle_offset`. Codes 0 and 7 set the sticky `error` once a valid code has
been seen. By default (`interpolate=True`) it measures the time between sector edges and ramps the
angle inside the sector, clamped at its boundary.

The resolver-to-digital converter, `LiteDSPResolverDigital`, generates the excitation sine on
`source_exc`, with one period every `decimation` samples. It demodulates the two windings
synchronously over one excitation period, vectors the sums with a CORDIC and smooths the raw angle
with an internal angle tracker.

The resolver's only calibration is `phase_offset`: for an analogue loop delay of `k` samples,
set it to `decimation - k`, since the demodulation reference is read `phase_offset` samples ahead,
modulo one excitation period. A
wrong offset lowers the demodulated amplitude, read as `raw_mag`, without biasing the angle. The
calibration therefore maximizes `raw_mag`.

The angle tracker, `LiteDSPAngleTracker`, is a type-II loop on an angle stream. Per sample, the
wrapped error drives a PI loop with shift gains (`kp_shift`, `ki_shift`); its integrator is the
`speed`. The lock time is about `6·2**(ki_shift - kp_shift)` samples, and `angle_offset`
compensates a sensor misalignment or an observer lag.

The sliding-mode observer, `LiteDSPSMObserver`, consumes the measured currents and the applied
voltages together, both on `iq_layout` in the `α`/`β` frame. It updates a current model per
axis, `ih += g_v·(v - emf - z) - g_r·ih`, with the sliding term `z = k_sm·sign(ih - i)` and a
low-pass filtered back-EMF `emf += (z - emf) >> lpf_shift`.

The observer emits the back-EMF angle, `atan2(-emf_α, emf_β)`, through a CORDIC. That is the
rotor angle for a positive speed; the sign of the tracker's speed resolves the negative case. Its
latency is `stages + 3` cycles.

The sliding gain `k_sm` is set for the operating point, at roughly half the back-EMF magnitude.
Too small a gain loses the sliding regime; too large a gain adds chatter at low speed. The
estimate lags the rotor by a constant that the filter phase bounds; the tracker's `angle_offset`
removes it.

## The FOC composite {#mot-foc}

The FOC composite, `LiteDSPFOC`, is the complete current controller: phase currents and rotor
angle in, three-phase duties out. The figure below shows its blocks and the angle path that feeds
both rotations.

![The FOC composite. The currents pass through Clarke, Park, the d/q controller, inverse Park and
the SVPWM modulator; one sin/cos sample per angle feeds Park directly and inverse Park through a
delay matched to the Park and controller latency.](mot_foc.svg)

The two rotations must use the same sin/cos sample, which the inverse Park needs later than the
Park. A split gives both branches the same sample, and a delay of the Park plus controller
latency holds the second copy. This is the delay-balancing rule the flow tool applies to reconvergent branches
([Latency and delay balancing](#pri-delay-balance)); it keeps the composite deadlock-free.

Both sinks, `sink` for the currents and `sink_angle` for the angle, are consumed together. The
fixed latency is `1 + 2 + (1 or 2) + 2 + 3` cycles: 9 without decoupling. The `speed` input feeds
the decoupling feed-forward when it is built.

The registers of the d/q controller (prefix `dq_`: setpoints, Q4.12 gains, limit, open-loop
vector, control, status and integrators) and of the modulator (`svpwm_control.injection`) form
the control surface of the composite; [Motor control](#reg-motor) lists them.

The constructor parameters are those of its parts: `data_width`, `angle_width`, `lut_depth`,
`three_wire`, `gain_width`, `gain_frac`, `anti_windup` and `decoupling`. The composite always
uses the ROM sin/cos.

## The loop is paced by the PWM {#mot-paced}

Feeding the PWM from the FOC composite runs the whole chain at the PWM rate through
backpressure alone ([sample point](#mpri-pwm)). The figure below shows the loop.

![The PWM-paced loop. The PWM trigger marks the sample point; the current sense and the position
decoder deliver one sample on it; the FOC composite computes the duties, and the PWM accepts them
at the next valley.](mot_loop.svg)

The trigger output marks the ADC sample point: a carrier value and a slope, the peak for
low-side shunts. A quadrature or Hall decoder emits its angle on the same strobe. The
sigma-delta current sense produces its currents at `1/rate` of the bit rate, so the host sets the
rate to give one sample per period.

The controller output reaches the PWM before the next valley and is applied there: one period of
control delay, as in any digital drive. The PWM's `missed` flag detects a loop that did not
deliver in time.

## Bring-up sequence {#mot-bringup}

A drive is brought up in steps, each one checking a part of the loop before the next closes it.
The register names below are those of the FOC composite and of the sensor blocks.

1. **Open loop.** Set `dq_control.open_loop` to 1 and a small vector in `dq_voltage_q`, with the
   angle from `LiteDSPAngleRamp` at a constant electrical frequency. The motor turns in V/f mode.
   Check the phase currents with a capture block and the gate signals.
2. **Current loop.** With the rotor locked, or the angle from the sensor, clear `open_loop` and
   step `dq_setpoint_q`. Tune `kp` and `ki` on the captured `i_q`. The pole-cancelling design
   `ki/kp = R/L·Ts` gives a first-order response.
3. **Sensor alignment.** Adjust the decoder's `angle_offset` until `i_d` is close to zero at
   steady state. For a resolver, adjust `phase_offset` for the largest `raw_mag`.
4. **Speed loop.** Close it on the host, or with a `LiteDSPPIController` and a
   `LiteDSPSlewLimiter` on the reference. For sensorless operation, switch to the observer and
   tracker angle above the lowest observable speed, with `k_sm` near half the back-EMF.
The capture blocks are in [Stream utilities and host links](#stream-frontend).

## Protection {#mot-protection}

The protection path is described with the trip in [Current sensing](#mot-sensing).

## Host side {#mot-host}

The typed drivers of `litedsp/software/drivers.py` convert between per-unit or physical values
and register words. Each driver binds the registers `<prefix>_<name>` of one block instance.

| Driver | Methods |
|-------------------------------------|-------------------------------------------------------------|
| `FOCDriver` | `set_setpoints`, `set_gains`, `set_limit`, `set_open_loop`, `clear`, `saturated` |
| `PWMDriver` | `set_frequency`, `set_dead_time`, `enable`, `clear_fault`, `set_trigger`, `fault` |
| `QuadratureDecoderDriver` | `configure`, `get_position`, `get_speed_rpm` |
| `AngleTrackerDriver` | `set_offset_degrees`, `set_bandwidth`, `get_speed_raw` |

`FOCDriver` takes per-unit floats and converts them to Q1.15 samples and Q4.12 gains; a gain
outside the Q4.12 range saturates (just under 8.0).
`PWMDriver` takes a frequency in hertz and a dead time in seconds, which needs `clk_freq`.
`QuadratureDecoderDriver.configure()` computes `angle_scale` from the counts per turn, as the
block expects. `PWMDriver.set_trigger()` and `QuadratureDecoderDriver.get_speed_rpm()` assume the
default `period_width` and `speed_width` of 16 bits. The driver chapter is [Using the application
families](#apps-using).

## Verification {#mot-verification}

Every motor block has a bit-exact golden model in `test/models.py` (the FOC model composes the
block models) and runs under randomized backpressure; the stream blocks except the resolver are
co-simulated with Verilator, and the pin-level blocks have cycle-exact register models
([Verification](#verification)).

## AN009: PMSM field-oriented control {#mot-an009}

The application note closes a complete current and speed loop around a per-unit motor model. The
RTL blocks run in Migen simulation; the motor, the inverter and the speed regulator are Python.
The example is `examples/foc_pmsm.py`.

It shows three ways of getting the rotor angle into the loop: an ideal sensor, the RTL
quadrature decoder fed from emulated A/B pins, and sensorless operation with the observer and
tracker after an open-loop V/f start. The figure below shows the setup.

![The AN009 setup. The FOC composite and the PWM are RTL; the PMSM model integrates each period
with the duties the PWM accepted and returns the currents. Each variant is its own build: the
angle comes from the model, from the quadrature decoder fed with emulated A/B pins, or, in the
sensorless build, from a mux that switches from the angle ramp to the observer and
tracker.](mot_an009.svg)

The PWM's one-sample-per-period acceptance paces the simulation as it paces hardware. The plant
waits for the carrier valley, integrates the period that just started with the duties the PWM
accepted, and hands the new currents to the controller. The controller output reaches the PWM
before the next valley.

### Models and loops {#mot-an009-models}

The motor model is a rotor-frame PMSM in per-unit, with `R` 0.05, `L` 0.3, `ψ` 0.6, `J` 2.0,
`B` 0.02 and a load torque `T_load` of 0.1, and `ω_b·Ts` = 0.05 rad per period, in 4 Euler
sub-steps per period. The equations of one step
are these:

- `i_d' = i_d + Ts/L·(v_d - R·i_d + ω·L·i_q)`
- `i_q' = i_q + Ts/L·(v_q - R·i_q - ω·L·i_d - ω·ψ)`
- `ω' = ω + Ts/J·(ψ·i_q - T_load - B·ω)`

The inverter is an average-value model: the duties are phase voltages in units of `V_dc/2`.

The current loop is a pole-cancelling PI. In per-unit, the rule reads `ki/kp = R_pu/L_pu·ω_b·Ts`,
the same ratio as `R/L·Ts`: `kp` is 1.5 and `ki` is 0.0125, which places the closed-loop pole at `1
- ω_b·Ts/L·kp` = 0.75. These per-unit gains map directly to the Q4.12 registers. The PWM half period
is 24 cycles, so a control period lasts 48 cycles of simulation.

The speed loop, the firmware, is a Python PI that writes `dq_setpoint_q`, as a CPU would.

The encoder variant emulates a 1024-count incremental encoder on a 2 pole-pair motor. It toggles
A and B from the mechanical angle; the RTL decoder's 4x count, pole-pair scaling and reciprocal
multiply feed the controller on the PWM trigger.

The sensorless variant runs 120 periods of open-loop V/f: `dq_control.open_loop` with a 0.25
per-unit vector, and the angle ramp at 0.25 per-unit speed. The firmware then switches a channel
mux to the observer angle and closes the loops. The sliding gain is set for the target operating
point.

The note is a demonstration: no switching ripple, dead time, sense delay or ADC noise, no field
weakening, a first-order mechanical model and a fixed sliding gain.

### Running it {#mot-an009-run}

The example prints its gates and `PASS`, and writes the figure of the results. Without
`--plot-dir`, the figure goes to `doc/app_notes/img/`, the committed copy of the note; pass
`--plot-dir <dir>` to keep the working tree clean. The output below is a run on the default 320
periods (Migen simulation, the plot path trimmed):

```console
$ python3 examples/foc_pmsm.py
[ideal     ] speed 0.501 pu (target 0.5), settled after 88 periods, |i_d| max 0.006 pu (settled), i_q peak 0.764 pu
[encoder   ] speed 0.501 pu (target 0.5), settled after 88 periods, |i_d| max 0.009 pu (settled), i_q peak 0.764 pu
             angle error after settling: mean -1.9, RMS 0.2 deg el.
[sensorless] speed 0.503 pu (target 0.5), settled after 210 periods, |i_d| max 0.101 pu (settled), i_q peak 1.061 pu
             angle error after settling: mean +0.0, RMS 2.0 deg el.
  PASS: speed settles within 2 % for ideal / encoder / sensorless sensing, |i_d| < 0.08 pu (0.15 sensorless) once settled, encoder angle RMS < 3 deg, sensorless angle RMS < 10 deg
  plots -> [...]/an009_foc.png
```

### Results {#mot-an009-results}

The settling is the number of periods until the speed stays within 2 % of its 0.5 per-unit
target; the `PASS` line lists the gates, and the example also asserts an `i_q` overshoot below
10 %. The current loop follows its first-order design: in the ideal and encoder variants, the
`i_q` step settles in a few periods without overshoot. The encoder's small mean error is the
one-period sample lag plus the count quantization.

In the sensorless variant, the open-loop V/f start draws an uncontrolled current, with an `i_q`
peak of 1.061 per-unit at the switch-over. The observer angle then takes over with a constant lag,
which a calibrated tracker offset of +14° removes. The remaining chatter costs about 0.1 per-unit
of `d`-axis current, the usual price of a fixed sliding gain. The figure below is the plot the
example writes.

![AN009 results (simulation): phase currents, speed and angle error of the three variants, from
`examples/foc_pmsm.py --plot-dir`.](mot_an009_foc.png)

Where to go next: [Audio blocks](#audio); the FOC as a standalone core in [Standalone
cores](#apps-cores); its synthesis results in [Motor control](#perf-motor).
