# Swap I/Q

`LiteDSPSwapIQ` — `litedsp.stream.ops` — category `stream`

latency: 0 samples · CSR: no · bypass: no

## Overview

Swap I and Q (a +/-90 deg rotation / spectrum mirror).

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

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_ops.py` (bit-exact/SNR under randomized backpressure).
