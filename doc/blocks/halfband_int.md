# Halfband interpolator

`LiteDSPHalfbandInterpolator` — `litedsp.filter.halfband` — category `filter`

latency: 23 samples · CSR: yes · bypass: no

## Overview

Interpolate-by-2 half-band FIR.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `23` | int | Number of FIR taps. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `core_config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `taps` | `0` | FIR taps N. |
| `[31:16]` | `rate` | `0` | Interpolation factor L. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_halfband.py` (bit-exact/SNR under randomized backpressure).
