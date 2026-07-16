# Moving average

`LiteDSPMovingAverage` — `litedsp.filter.moving_average` — category `filter`

latency: 1 sample · CSR: no · bypass: yes

## Overview

Boxcar moving average over ``2**length_log2`` samples (per I/Q), a.k.a. CIC-1.

Maintains a running sum ``acc += x[n] - x[n-L]`` with an L-deep delay line (single adder),
and outputs the rounded average ``acc / L``. Output stays in the input range, so no
saturation is needed.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `length_log2` | `4` | int | log2 of the averaging length (L = 2**length_log2 samples, must be >= 1). Sets the per-I/Q delay-line memory depth and adds length_log2 + 1 accumulator guard bits. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 246 | 87 | 0 | 0 | 157.1 |
| xilinx | 172 | 85 | 0 | 0 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).
