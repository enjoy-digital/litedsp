# CRC

`LiteDSPCRC` — `litedsp.comm.coding` — category `comm`

latency: 1 sample · CSR: no · bypass: no

## Overview

Bit-serial MSB-first CRC; passes ``data`` through and updates the ``crc`` register.

``clear`` re-initializes the register to ``init``. Defaults: CRC-16-CCITT
(poly 0x1021, init 0xFFFF).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `width` | `16` | int | CRC register width in bits (16 for the CRC-16-CCITT default). |
| `poly` | `4129` | int | Generator polynomial, MSB-first with the implicit x^width term omitted (default 0x1021 = x^16 + x^12 + x^5 + 1). |
| `init` | `65535` | int | Value loaded into the CRC register at reset and on ``clear`` (default 0xFFFF). |

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
