# Combine (sum)

`LiteDSPCombine` — `litedsp.stream.combine` — category `stream`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Sum ``n_channels`` complex I/Q streams into one, with per-channel enable and saturation.

The internal accumulator grows to fit the worst-case sum (``data_width + ceil(log2(N))``)
so it never wraps, then the result is saturated back to ``data_width`` — unlike the
original tetra ``Sum`` which could silently overflow. All enabled inputs are consumed
together (synchronous join); output appears after a fixed 1-cycle latency.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_channels` | `2` | int | Number of I/Q input streams summed (>= 1). Adds ceil(log2(n_channels)) accumulator guard bits before saturation; all inputs must present a sample for any to transfer. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sinks[0]` | sink | iq |
| `sinks[1]` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `enable` (read-write, 2 bits, reset `0x3`)

Per-channel enable mask (bit k enables channel k).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 327 | 33 | 0 | 0 | 281.6 | — |
| xilinx | 134 | 33 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_combine.py` (bit-exact/SNR under randomized backpressure).
