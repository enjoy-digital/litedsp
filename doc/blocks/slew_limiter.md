# Slew limiter

`LiteDSPSlewLimiter` — `litedsp.motor.limiter` — category `motor`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Rate limiter for references (speed/torque ramps): ``y += clamp(x - y, +/-rate)``.

The output follows the input at most ``rate`` per accepted sample (a trapezoidal ramp
generator when fed a setpoint step), reaching a step of size ``D`` in exactly
``ceil(D/rate)`` samples with no overshoot. ``rate`` is a positive per-sample increment
(reset: full scale = limiter off); ``bypass`` passes the input through. Fixed 1-cycle
latency, no multiplier.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `rate` (read-write, 16 bits, reset `0x7fff`)

Maximum change per sample (positive; full scale disables the limiter).

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 141 | 35 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_limiter.py` (bit-exact/SNR under randomized backpressure).
