# Differential encoder

`LiteDSPDifferentialEncoder` — `litedsp.comm.diff` — category `comm`

latency: 1 sample · CSR: no · bypass: no

## Overview

``out[n] = (in[n] + out[n-1]) mod M`` (symbol indices).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `modulus` | `4` | int | Number of symbol values M; arithmetic wraps mod M on ceil(log2(M))-bit symbol indices (2 = DBPSK, 4 = DQPSK). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_diff.py` (bit-exact/SNR under randomized backpressure).
