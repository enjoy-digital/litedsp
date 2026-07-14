# Upsampler

`LiteDSPUpsampler` — `litedsp.rate.dropper` — category `rate`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Emit ``factor`` I/Q samples per input: sample-and-hold (default) or zero-stuff.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `factor_bits` | `16` | int | Width in bits of the runtime ``factor`` control/CSR; the maximum interpolation factor is 2**factor_bits - 1 (factor itself is set at runtime, reset value 1). |
| `zero_stuff` | `False` | bool | Insert zeros between input samples instead of repeating the held value (build-time choice); pair with an anti-image filter sized for the zero-stuff spectral images. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `factor` (read-write, 16 bits, reset `0x1`)

Interpolation factor (emit N samples per input).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_dropper.py` (bit-exact/SNR under randomized backpressure).
