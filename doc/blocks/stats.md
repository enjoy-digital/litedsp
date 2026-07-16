# Stats

`LiteDSPStats` — `litedsp.analysis.stats` — category `analysis`

latency: 1 sample · CSR: no · bypass: no

## Overview

Min / max / mean / variance of a real stream over ``2**window_log2`` samples.

Emits one result per window on ``source`` (fields ``min, max, mean, variance``). Input is
always accepted; the latest completed result is held until consumed.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `window_log2` | `8` | int | Samples per measurement window as a power of two (one result every ``2**window_log2`` samples); sizes the running-sum and sum-of-squares accumulators (log2(N)-bit growth). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | raw |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 289 | 186 | 0 | 2 | 113.2 |
| xilinx | 92 | 114 | 0 | 3 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).
