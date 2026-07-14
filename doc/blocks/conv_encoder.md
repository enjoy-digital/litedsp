# Convolutional encoder

`LiteDSPConvEncoder` — `litedsp.comm.coding` — category `comm`

latency: 1 sample · CSR: no · bypass: no

## Overview

Rate-1/2 convolutional encoder (default K=7, G=[0o171, 0o133]).

One input bit -> two coded bits on ``source.data`` (``[g1 | g0]``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `constraint` | `7` | int | Constraint length K of the convolutional code (shift-register memory = K-1 bits). |
| `polys` | `(121, 91)` | list | Generator polynomials, octal, one output bit each (rate = 1/len(polys); default (0o171, 0o133): the CCSDS/Voyager K=7 pair). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_coding.py` (bit-exact/SNR under randomized backpressure).
