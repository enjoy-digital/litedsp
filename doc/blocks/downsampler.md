# Downsampler

`LiteDSPDownsampler` — `litedsp.rate.dropper` — category `rate`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Keep one of every ``factor`` I/Q samples (naive decimation, no anti-alias filter).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `factor_bits` | `16` | int | Width in bits of the runtime ``factor`` control/CSR; the maximum decimation factor is 2**factor_bits - 1 (factor itself is set at runtime, reset value 1). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `factor` (read-write, 16 bits, reset `0x1`)

Decimation factor (keep 1 of every N samples).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_dropper.py` (bit-exact/SNR under randomized backpressure).
