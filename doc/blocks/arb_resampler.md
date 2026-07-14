# Arbitrary resampler

`LiteDSPArbResampler` — `litedsp.filter.arb_resampler` — category `filter`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Arbitrary (non-rational) sample-rate conversion via cubic Farrow + a phase accumulator.

``ratio = f_in / f_out`` (Q.``frac``): each output advances the fractional phase by ``ratio``;
whenever the integer part rolls over, one input sample is consumed (window shifts). The
output is a Catmull-Rom interpolation at the fractional phase. ``ratio < 1`` interpolates,
``> 1`` decimates (precede with an anti-alias filter when decimating).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `frac` | `15` | int | Fractional bits of the control fixed-point format. |
| `ratio_int_bits` | `8` | int | Integer bits of the ratio/phase registers (total width = frac + ratio_int_bits); bounds the maximum decimation ratio f_in/f_out at just under 2**ratio_int_bits. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `ratio` (read-write, 23 bits, reset `0x8000`)

Resampling ratio f_in/f_out (Q.frac).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_arb_resampler.py` (bit-exact/SNR under randomized backpressure).
