# Angle ramp

`LiteDSPAngleRamp` — `litedsp.motor.transforms` — category `motor`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Free-running electrical-angle source: a phase accumulator emitting an angle stream.

``angle`` advances by ``phase_inc`` (top ``angle_width`` bits of a ``phase_bits``
accumulator) per accepted sample, so backpressure never skips or repeats a step. Drives the
open-loop / V/f bring-up of a drive (constant-frequency rotating voltage vector) and the
transform tests; set ``phase_inc = f_e / f_ctrl * 2**phase_bits`` for an electrical
frequency ``f_e`` at control rate ``f_ctrl``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `angle_width` | `16` | int |  |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | angle |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `phase_inc` (read-write, 32 bits)

Angle increment per sample (2**phase_bits = one electrical turn).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_transforms.py` (bit-exact/SNR under randomized backpressure).
