# PI controller

`LiteDSPPIController` — `litedsp.motor.pi` — category `motor`

latency: 1 sample · CSR: yes · bypass: no

## Overview

PI regulator on a real stream: ``u = clamp(kp*e + integral + feedforward, +/-limit)``.

Per accepted measurement ``y``: ``e = setpoint - y``; the output uses the current
integrator (``integral += ki*e`` afterwards, as synchronous hardware does), is rounded
once from the ``gain_frac`` domain and clamped to ``+/-limit``. Gains are signed
Q(gain_width-gain_frac).gain_frac (Q4.12 by default: 1.0 = 4096); ``limit`` is a positive
magnitude (reset: full scale). Anti-windup: ``"conditional"`` stops integrating while the
output is clamped in the direction of the error (integrator never winds up, immediate
recovery), ``"clamp"`` only bounds the integrator to ``+/-limit``, ``"none"`` lets it
wrap (for reference only). ``open_loop`` forwards ``feedforward`` (clamped) and holds the
integrator at zero (bring-up); ``clear`` zeroes the integrator; ``saturated`` is a
sticky clamp flag. With ``setpoint_stream=True`` the setpoint arrives on ``sink_ref``
(joined with ``sink``) instead of the ``setpoint`` control. Fixed 1-cycle latency.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `gain_width` | `16` | int | Width of the signed ``kp``/``ki`` gains. |
| `gain_frac` | `12` | int | Fractional bits of the gains (1.0 = 2**gain_frac); must be < gain_width. |
| `anti_windup` | `"conditional"` | str | ``"conditional"`` (default), ``"clamp"`` or ``"none"``. Choices: `conditional`, `clamp`, `none`. |
| `setpoint_stream` | `False` | bool | Take the setpoint from a ``sink_ref`` stream (sample-aligned join) instead of a control. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `setpoint` (read-write, 16 bits)

Setpoint (signed, per-unit).

### `kp` (read-write, 16 bits, reset `0x1000`)

Proportional gain (signed Q4.12).

### `ki` (read-write, 16 bits)

Integral gain per sample (signed Q4.12).

### `limit` (read-write, 16 bits, reset `0x7fff`)

Output magnitude limit (positive, per-unit).

### `feedforward` (read-write, 16 bits)

Feed-forward term added to the output (the open-loop command).

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `open_loop` | `0` | Output = feedforward; integrator held at 0. |
| `[1]` | `clear` | `0` | Zero the integrator. (pulse) |
| `[2]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturated` | `0` | Output clamped since the last clear. |

### `integral` (read-only, 30 bits)

Integrator state (Q.gain_frac).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 514 | 50 | 0 | 2 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_pi.py` (bit-exact/SNR under randomized backpressure).
