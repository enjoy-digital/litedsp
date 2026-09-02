# d/q current controller

`LiteDSPDQController` — `litedsp.motor.pi` — category `motor`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Two lock-stepped PI regulators on a d/q current vector -> d/q voltage command.

``sink`` carries the measured ``(i_d, i_q)`` on ``iq_layout`` (i = d, q = q), ``source``
the voltage command ``(v_d, v_q)``. Each axis is a :class:`LiteDSPPIController` with its
own setpoint and gains and a shared ``limit``. ``open_loop`` forwards ``voltage_d/q``
(the bring-up vector). With ``decoupling=True`` the PMSM cross-coupling terms are added as
feed-forward from the per-unit ``speed`` input (electrical, 1.0 = base speed) and the
``l_pu``/``psi_pu`` constants: ``ff_d = -w*L*i_q`` and ``ff_q = w*(L*i_d + psi)`` with
``L_pu = w_b*L*I_b/V_b`` and ``psi_pu = w_b*psi/V_b`` (one extra registered stage).
Latency 1 (2 with decoupling).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `gain_width` | `16` | int | Width of the signed gains. |
| `gain_frac` | `12` | int | Fractional bits of the gains (1.0 = 2**gain_frac). |
| `anti_windup` | `"conditional"` | str | Integrator anti-windup of both regulators: ``"conditional"``, ``"clamp"`` or ``"none"``. Choices: `conditional`, `clamp`, `none`. |
| `decoupling` | `False` | bool | Add the speed-dependent cross-coupling feed-forward (needs ``speed``, ``l_pu``, ``psi_pu``). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `setpoint_d` (read-write, 16 bits)

d-axis current setpoint (per-unit).

### `setpoint_q` (read-write, 16 bits)

q-axis current setpoint (per-unit).

### `kp_d` (read-write, 16 bits, reset `0x1000`)

d-axis proportional gain (signed Q4.12).

### `ki_d` (read-write, 16 bits)

d-axis integral gain per sample (signed Q4.12).

### `kp_q` (read-write, 16 bits, reset `0x1000`)

q-axis proportional gain (signed Q4.12).

### `ki_q` (read-write, 16 bits)

q-axis integral gain per sample (signed Q4.12).

### `limit` (read-write, 16 bits, reset `0x7fff`)

Voltage magnitude limit per axis (positive, per-unit).

### `voltage_d` (read-write, 16 bits)

Open-loop d voltage (bring-up).

### `voltage_q` (read-write, 16 bits)

Open-loop q voltage (bring-up).

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `open_loop` | `0` | Output = voltage_d/q; integrators held at 0. |
| `[1]` | `clear` | `0` | Zero both integrators. (pulse) |
| `[2]` | `clear_sat` | `0` | Clear the saturation flags. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturated_d` | `0` | d output clamped since the last clear. |
| `[1]` | `saturated_q` | `0` | q output clamped since the last clear. |

### `integral_d` (read-only, 30 bits)

d integrator (Q.gain_frac).

### `integral_q` (read-only, 30 bits)

q integrator (Q.gain_frac).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 925 | 98 | 0 | 4 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_pi.py` (bit-exact/SNR under randomized backpressure).
