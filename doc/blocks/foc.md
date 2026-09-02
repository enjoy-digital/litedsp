# FOC current controller

`LiteDSPFOC` — `litedsp.motor.foc` — category `motor`

latency: 9 samples · CSR: yes · bypass: no

## Overview

Field-oriented current control: phase currents + rotor angle -> three-phase duties.

``sink`` (measured a/b/c currents) goes through the Clarke transform, the Park rotation
(complex mixer, down) by the sin/cos of ``sink_angle``, the d/q PI current controller
(:class:`~litedsp.motor.pi.LiteDSPDQController`: setpoints, gains, limit, open-loop
bring-up vector and optional decoupling via ``speed``), the inverse Park rotation (mixer,
up) by the *same* sin/cos sample (an atomic fan-out plus a delay matched to the Park +
controller latency keeps the two rotations sample-aligned and deadlock-free) and the
space-vector modulator; ``source`` carries the duties for :class:`~litedsp.motor.pwm.
LiteDSPPWM`, whose one-sample-per-period acceptance paces the whole loop. Both sinks are
consumed together. The controller's CSRs (``dq_*``) and the modulator's (``svpwm_*``) are
the block's control surface; ``dq_control.open_loop`` is the bring-up mode. Fixed latency
``1 + 2 + (1|2) + 2 + 3`` cycles.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `angle_width` | `16` | int | Rotor angle width (full turn = 2**angle_width). |
| `lut_depth` | `1024` | int | Sin/cos ROM entries per turn. |
| `three_wire` | `False` | bool | Two measured currents (``c = -a - b``) in the Clarke transform. |
| `gain_width` | `16` | int |  |
| `gain_frac` | `12` | int |  |
| `anti_windup` | `"conditional"` | str | Controller integrator anti-windup: ``"conditional"``, ``"clamp"`` or ``"none"``. Choices: `conditional`, `clamp`, `none`. |
| `decoupling` | `False` | bool | Cross-coupling feed-forward from ``speed`` in the controller. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | abc |
| `sink_angle` | sink | angle |
| `source` | source | abc |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `dq_setpoint_d` (read-write, 16 bits)

d-axis current setpoint (per-unit).

### `dq_setpoint_q` (read-write, 16 bits)

q-axis current setpoint (per-unit).

### `dq_kp_d` (read-write, 16 bits, reset `0x1000`)

d-axis proportional gain (signed Q4.12).

### `dq_ki_d` (read-write, 16 bits)

d-axis integral gain per sample (signed Q4.12).

### `dq_kp_q` (read-write, 16 bits, reset `0x1000`)

q-axis proportional gain (signed Q4.12).

### `dq_ki_q` (read-write, 16 bits)

q-axis integral gain per sample (signed Q4.12).

### `dq_limit` (read-write, 16 bits, reset `0x7fff`)

Voltage magnitude limit per axis (positive, per-unit).

### `dq_voltage_d` (read-write, 16 bits)

Open-loop d voltage (bring-up).

### `dq_voltage_q` (read-write, 16 bits)

Open-loop q voltage (bring-up).

### `dq_control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `open_loop` | `0` | Output = voltage_d/q; integrators held at 0. |
| `[1]` | `clear` | `0` | Zero both integrators. (pulse) |
| `[2]` | `clear_sat` | `0` | Clear the saturation flags. (pulse) |

### `dq_status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturated_d` | `0` | d output clamped since the last clear. |
| `[1]` | `saturated_q` | `0` | q output clamped since the last clear. |

### `dq_integral_d` (read-only, 30 bits)

d integrator (Q.gain_frac).

### `dq_integral_q` (read-only, 30 bits)

q integrator (Q.gain_frac).

### `svpwm_control` (read-write, 1 bit, reset `0x1`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `injection` | `1` |  ``0b0``: Sinusoidal modulation (no zero sequence).; ``0b1``: Space-vector (min/max zero-sequence injection). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 2777 | 760 | 0 | 15 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_foc.py` (bit-exact/SNR under randomized backpressure).
