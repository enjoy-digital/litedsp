# Farrow interpolator

`LiteDSPFarrowInterpolator` — `litedsp.filter.farrow` — category `filter`

latency: 7 samples · CSR: yes · bypass: no

## Overview

Cubic (Catmull-Rom) Farrow fractional-delay interpolator with runtime ``mu``.

Interpolates between samples at fractional position ``mu`` (Q.``frac_bits``, 0..1) using a
4-tap window via Horner evaluation. The Catmull-Rom coefficients are all multiples of 1/2,
so no awkward divides are needed. One output per input (a fractional delay); pair with a
phase accumulator for arbitrary-ratio resampling.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `frac_bits` | `15` | int | Fractional bits of the coefficient/control fixed-point format. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `mu` (read-write, 15 bits)

Fractional delay (Q.frac).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 808 | 922 | 0 | 16 | 106.4 | — |
| xilinx | 678 | 443 | 0 | 6 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_farrow.py` (bit-exact/SNR under randomized backpressure).
