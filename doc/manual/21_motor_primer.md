# Motor control in a nutshell {#motor-primer}

This chapter explains field-oriented control of a permanent-magnet motor to an FPGA engineer who
has never tuned a drive. It starts from the machine and the inverter, builds the reference frames
and the control loops, then covers modulation, sensors, protection and per-unit scaling.

Each section gives the idea, then the mechanism, and ends with the LiteDSP block that implements
it. [Motor control blocks](#motor) then describes the blocks themselves and how they connect.

## The machine and the inverter {#mpri-machine}

A permanent-magnet synchronous motor (PMSM) has magnets on its rotor and three windings on its
stator, 120 degrees apart. Currents in the windings create a magnetic field; the rotor turns to
align its magnets with that field. To keep it turning, the stator field must rotate ahead of the
rotor, synchronously with it.

A brushless DC motor (BLDC) is the same machine, often wound for a trapezoidal back-EMF and driven
by switching two phases at a time from Hall sensors. Field-oriented control drives it with
sinusoidal currents instead, which gives smoother torque. The LiteDSP blocks treat both as a
PMSM.

The windings are driven by an *inverter*: three half-bridges, one per phase, each with a high-side
and a low-side transistor between the two rails of a DC bus. The figure below shows it. Each
half-bridge connects its phase either to the positive rail or to the negative rail.

![A three-phase inverter. Each of the three half-bridges connects one motor phase to the positive
or the negative rail of the DC bus; the PWM generator drives the six gate signals, and the
current sensors measure the phase currents.](mpri_inverter.svg)

Switching fast between the two rails with a varying duty cycle sets the *average* voltage of a
phase anywhere between the rails. This is pulse-width modulation (PWM). The winding inductance
filters the switching, so the current follows the average voltage.

The two transistors of a half-bridge must never conduct together: that would short the DC bus.
Every switching edge therefore inserts a *dead time*, a short interval with both transistors
off. The PWM generator, `LiteDSPPWM`, inserts it on every edge.

## Torque, current and back-EMF {#mpri-torque}

The torque of a PMSM is proportional to the component of the stator current that is at 90
electrical degrees from the rotor magnets. The component aligned with the magnets produces no
torque; it only strengthens or weakens the field. Controlling torque is therefore controlling
the current *vector*, relative to the rotor position.

A turning rotor induces a voltage in the windings, the *back-EMF*, proportional to the speed and
to the flux linkage of the magnets `ψ`. The inverter must supply that voltage plus the resistive
and inductive drops. At high speed the back-EMF approaches the DC bus voltage, which bounds the
speed reachable with a given bus.

A motor has `p` *pole pairs*: the magnetic pattern repeats `p` times per mechanical turn. The
control works in *electrical* angle, which turns `p` times faster than the shaft. The encoder
decoder of LiteDSP converts a mechanical count into an electrical angle with its `pole_pairs`
setting.

## Reference frames: Clarke and Park {#mpri-frames}

Three phase currents carry only two independent values when they sum to zero, as in a motor with
no neutral connection. The *Clarke transform* maps the three phase values `a`, `b`, `c` onto two
orthogonal axes `α` and `β` of a stationary plane. The resulting *space vector* `α + jβ` turns
at the electrical frequency.

LiteDSP uses the amplitude-invariant form: `α = (2a - b - c)/3` and `β = (b - c)/√3`. A balanced
set of phase peak `A` gives a vector of magnitude `A`. With two measured currents, the third is
implied (`c = -a - b`): then `α = a` exactly and `β = (a + 2b)/√3`.

The *Park transform* rotates the space vector by the rotor angle `θ` into a frame that turns with
the rotor: `d + jq = (α + jβ)·e^(-jθ)`. The `d` axis is aligned with the magnets and the `q` axis
is at 90 degrees.

In steady state, `d` and `q` are constant: the sinusoidal phase currents become two DC values. The
figure below shows the chain.

![From phase quantities to rotor-frame quantities. The Clarke transform maps the three phases onto
the stationary α/β plane; the Park transform rotates that vector by the rotor angle into the d/q
frame, where steady-state currents are constant.](mpri_frames.svg)

Because the space vector is a complex number, the Park rotation is a complex multiplication by
`cos θ - j sin θ`: the down-conversion of a mixer. The inverse Park rotation multiplies by
`cos θ + j sin θ`, the up-conversion. LiteDSP builds both from its complex mixer and a sin/cos
lookup, as [Mixing](#pri-mixing) explains for radio signals.

In LiteDSP, the stationary and rotating vectors ride on the complex `iq_layout` (`i` is `α` or
`d`, `q` is `β` or `q`). The three-phase values use `abc_layout`, and angles use `angle_layout`.

## Field-oriented control {#mpri-foc}

Field-oriented control (FOC) regulates the `d` and `q` currents directly. Each control period it
measures the phase currents, reads the rotor angle, applies Clarke and Park, runs one regulator
per axis, rotates the voltage command back with the inverse Park transform and hands it to the
modulator.

The setpoint of `i_d` is usually zero, which gives the most torque per ampere for a surface-magnet
motor. The setpoint of `i_q` is the torque command. An outer speed loop, when there is one,
computes that torque command from the speed error.

The figure below shows the usual cascade: a slow speed loop around a fast current loop. The
current loop runs once per PWM period; the speed loop often runs at a lower rate, in software.

![The FOC cascade. The speed regulator sets the q-current setpoint; the current regulators set the
d/q voltages; the inverse Park transform and the modulator turn them into phase duties for the
inverter. The rotor angle feeds both rotations.](mpri_cascade.svg)

At high speed the `d` and `q` axes interact: the voltage on one axis has a term proportional to
the speed times the current of the other. A *decoupling* feed-forward cancels these terms:
`ff_d = -ω·L·i_q` and `ff_q = ω·(L·i_d + ψ)`. The LiteDSP d/q controller adds it with its
`decoupling` option.

The loop also has a limit: the voltage vector cannot exceed what the DC bus can supply. Beyond
that point the regulators saturate. Field weakening, which injects a negative `i_d` to extend the
speed range, and MTPA, which optimizes the current split for interior-magnet motors, are outside
the blocks of LiteDSP.

## PI regulators and anti-windup {#mpri-pi}

Each current axis uses a proportional-integral (PI) regulator. Per sample, the error `e` is the
setpoint minus the measurement; the output is `kp·e` plus the integral of `ki·e`. The integral
removes the steady-state error that a proportional term alone leaves.

A current loop is a resistor-inductor plant with time constant `L/R`. Choosing `ki/kp = R/L·Ts`,
with `Ts` the control period, cancels the plant pole with the regulator zero. The closed loop
then behaves as a first-order system whose speed is set by `kp` alone. This *pole-cancelling*
design is the rule the LiteDSP examples and tests use.

When the output hits its limit, the integrator keeps accumulating an error that the actuator
cannot follow. When the error reverses, the loop has to unwind that excess first, which causes a
large overshoot. This is *windup*.

*Anti-windup* prevents it. Conditional integration stops the integrator while the output is
clamped in the direction of the error; clamping only bounds the integrator. The LiteDSP PI
regulator, `LiteDSPPIController`, offers both, conditional by default, plus a `"none"` mode for
reference.

A *slew limiter* complements the regulators on the reference side. It lets a setpoint move by at
most a fixed step per sample, so a speed or torque step becomes a ramp. The LiteDSP limiter,
`LiteDSPSlewLimiter`, reaches a step of size `D` in `ceil(D/rate)` samples without overshoot.

## Modulation: sinusoidal and space-vector PWM {#mpri-svpwm}

The modulator turns the `α`/`β` voltage command into three phase duties. Plain sinusoidal
modulation applies the inverse Clarke transform: each phase duty is a sine. Its linear range ends
when a phase peak reaches half the DC bus voltage.

Only the voltages between phases reach the windings, so the modulator may add the same value to
all three duties: a *zero sequence*. Space-vector modulation (SVPWM) adds `v0 = -(max + min)/2`,
which centres the three duties in the available range. The linear range then extends to a phase
peak of `2/√3`, about 1.1547 times the sinusoidal limit.

The LiteDSP modulator, `LiteDSPSVPWM`, computes the inverse Clarke transform two bits wider than
the samples, adds the min/max zero sequence when its `injection` control is set, and saturates the
duties to the full scale. Duty `-1.0` means 0 % and `+1.0` means 100 %.

## Centre-aligned PWM and the sample point {#mpri-pwm}

A centre-aligned PWM compares each phase duty with a triangular carrier that counts up and down.
In `LiteDSPPWM` a high-side gate is on while the carrier is below the compare value, so the three
high-side pulses are centred on the carrier valley and the three low-side pulses on the carrier
peak. At the peak all the low-side transistors conduct: the zero vector.

The zero vector is the best time to sample shunt currents. Low-side shunt resistors carry the
phase current only while the low-side transistor conducts, and the switching noise is away from
the peak. A drive with low-side shunts therefore triggers its ADC at a fixed carrier value near
the peak. The trigger register of `LiteDSPPWM` resets to the valley, which suits high-side or
in-line sensing only; the host driver selects the peak ([PWM](#mot-pwm)).

The PWM period is the natural control period. The controller computes one new set of duties per
period from the sampled currents; the PWM accepts them at a valley and applies them at the next
valley. The loop design accounts for this delay.

LiteDSP builds the whole loop on this rule. `LiteDSPPWM` accepts exactly one duty sample per
period, at the valley, so the stream contract itself paces every block upstream: there is no
sample counter and no clock-enable tree. [The loop is paced by the PWM](#mot-paced) describes it.

## Current sensing {#mpri-sensing}

A drive measures two or three phase currents. Shunt resistors with an ADC are the common choice.
Isolated drives often use *sigma-delta modulators* instead: a modulator on the high-voltage side
turns the current into a fast 1-bit stream, which crosses an isolation barrier as a digital
signal.

The FPGA recovers the current from that bitstream with a sinc filter, the same structure as a CIC
decimator ([CIC filters](#pri-cic)). A third-order sinc is the usual choice for current sense. The
decimation sets the trade-off: a long filter gives a precise current once per period; a short one
gives a coarse current within a few bits.

The LiteDSP current-sense block, `LiteDSPSigmaDeltaFilter`, uses both. A control path decimates
each phase at a runtime rate set so that one current sample lands per PWM period. A fast path, a
short sinc of fixed decimation per phase, compares the current against a threshold and trips
within a few modulator bits.

## Rotor position sensors {#mpri-sensors}

The Park rotation needs the electrical angle of the rotor at every sample. The figure below shows
the four sources a drive uses and the LiteDSP block for each.

![Rotor angle sources. An incremental encoder, Hall sensors and a resolver each have a decoder
block; a sensorless observer estimates the angle from currents and voltages. An angle tracker
smooths any of them into a clean angle and a speed; the resolver converter has its tracker built
in.](mpri_sensors.svg)

An *incremental encoder* has two square-wave outputs, A and B, in quadrature, plus an index pulse
once per turn. Counting every edge of both signals gives four counts per line: *4x decoding*. The
direction comes from which signal leads. An illegal transition, both signals changing at once,
indicates noise or a missed edge.

*Hall sensors* are three digital sensors 120 electrical degrees apart. Their code gives one of six
60-degree sectors. That is coarse, but at constant speed the time between sector edges gives the
speed, and the angle can be interpolated inside a sector.

A *resolver* is a rotary transformer. The drive excites its primary with a sine; two secondary
windings return that carrier modulated by the sine and the cosine of the angle. Synchronous
demodulation of both windings, then `atan2`, recovers the angle.

*Sensorless* control estimates the angle from the measured currents and the applied voltages.
LiteDSP uses a sliding-mode observer: a current model per axis, driven by a switching term
`k·sign(î - i)` that forces the model current onto the measured one. The low-pass filtered
switching term is the back-EMF, whose angle is the rotor angle.

The back-EMF vanishes at standstill, so a sensorless drive starts in open loop. It applies a
rotating voltage vector at a ramping frequency, a *V/f start*, then switches to the observer once
the speed gives a usable back-EMF. LiteDSP provides the rotating angle with `LiteDSPAngleRamp`.

All these raw angles are noisy or coarse. An *angle tracker*, a type-II phase-locked loop on the
angle, smooths them: it tracks a constant-speed input with zero steady-state error and its
integrator is the speed. This is the same structure as a carrier recovery loop.

## Protection {#mpri-protection}

An inverter fault can destroy the transistors much faster than a software loop reacts.
Protection is therefore a hardware path: an over-current comparator or a gate-driver fault input
switches all six gate signals off directly, and the drive stays off until the host clears
the fault.

In LiteDSP the fault input of `LiteDSPPWM` forces all six outputs low two clock cycles later and
latches. Both the window comparator, `LiteDSPOvercurrentTrip`, and the fast path of the
sigma-delta current sense, through its sticky `overcurrent` flags, can drive it.

## Per-unit scaling {#mpri-per-unit}

A drive works with currents in amperes, voltages in volts and speeds in radians per second, whose
ranges depend on the motor. *Per-unit* scaling divides every quantity by a base value, so that
the fixed-point datapath handles values around 1.0 whatever the motor.

| Base | Symbol | Typical choice |
|-----------------------|--------|-------------------------------------------------------|
| Current | `I_b` | Peak current rating of the inverter |
| Voltage | `V_b` | `V_dc/2`, the largest sinusoidal phase peak without over-modulation |
| Speed | `ω_b` | Rated electrical speed |
| Control period | `Ts` | One PWM period |

The per-unit plant constants and the current-loop gains follow from these bases and from the
pole-cancelling rule; [Conventions](#mot-conventions) of the block chapter lists the formulas.
In LiteDSP, currents, voltages, duties and the plant constants are signed Q1.15 values by
default (1.0 is the base value); the loop gains are signed Q4.12 (1.0 is 4096). Angles span a
full turn over `2**angle_width`, the convention of the NCO and the CORDIC ([The NCO](#pri-nco)).

Where to go next: [Motor control blocks](#motor) for the implementation, [Audio
primer](#audio-primer) for the next family.
