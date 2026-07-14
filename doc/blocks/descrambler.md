# Descrambler (LFSR)

`LiteDSPDescrambler` — `litedsp.comm.coding` — category `comm`

latency: 1 sample · CSR: no · bypass: no

## Overview

Inverse of :class:`LiteDSPScrambler` ``x = y ^ y[-t1] ^ y[-t2] ...`` (self-synchronizing).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `polynomial` | `(18, 23)` | list | Feedback tap positions, must match the scrambler's (default (18, 23): 1 + x^18 + x^23). State register length = max(taps) bits. |

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
