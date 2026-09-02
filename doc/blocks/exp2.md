# Exp2 (antilog)

`LiteDSPExp2` — `litedsp.level.logdb` — category `level`

latency: 2 samples · CSR: no · bypass: no

## Overview

Fixed-point ``2**v`` of a signed log2-domain value (ROM mantissa + integer shift).

The input ``v`` is signed Q(in_width-frac_bits).``frac_bits`` (the format of
:class:`LiteDSPLog2` outputs and dB-domain gains); the output is unsigned ``2**v`` in
Q(out_width-out_frac).``out_frac``, saturated at the top and rounded to zero at the bottom.
A ``2**frac_bits`` entry ROM gives ``2**(f/2**frac_bits)`` for the fractional part, the
integer part shifts it (left: saturating, right: rounding). The inverse of the log block
for gain computers (compressor make-up/reduction, dB volume). Latency 2.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `in_width` | `16` | int |  |
| `frac_bits` | `8` | int | Fractional bits of the coefficient/control fixed-point format. |
| `out_frac` | `20` | int |  |
| `out_width` | `25` | int |  |

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
