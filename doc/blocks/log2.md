# Log2

`LiteDSPLog2` — `litedsp.level.logdb` — category `level`

latency: 1 sample · CSR: no · bypass: no

## Overview

Fixed-point base-2 logarithm of an unsigned input (priority-encoder + mantissa).

``log2(x) ~= msb_position + fraction`` where the fraction is the ``frac_bits`` bits just
below the most-significant set bit (linear-in-mantissa approximation, error < ~0.086).
Output is ``log2`` in unsigned Q(int).``frac_bits``. ``x == 0`` yields 0.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `in_width` | `32` | int | Width in bits of the unsigned input. Sets the integer output bits (enough to encode the MSB index) and the size of the priority encoder / alignment shifter. |
| `frac_bits` | `8` | int | Fractional bits of the coefficient/control fixed-point format. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_logdb.py` (bit-exact/SNR under randomized backpressure).
