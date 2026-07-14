# Clipper

`LiteDSPClipper` — `litedsp.level.clipper` — category `level`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Hard limiter: clamp each of I/Q to +/- ``threshold`` (runtime). ``clip`` flags a clip.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

### `threshold` (read-write, 16 bits, reset `0x7fff`)

Clip threshold (magnitude).

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clip` | `0` | Clipping occurred. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_clipper.py` (bit-exact/SNR under randomized backpressure).
