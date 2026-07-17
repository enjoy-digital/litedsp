# Stream FIFO

`LiteDSPStreamFIFO` — `litedsp.stream.fifo` — category `stream`

latency: 0 samples · CSR: yes · bypass: no

## Overview

First-word-fall-through synchronous FIFO for an I/Q (or custom-``layout``) stream.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `depth` | `16` | int | FIFO capacity in stream beats (>= 1); size it to the largest burst the consumer can fall behind by, since a push while full sets the sticky ``overflow`` flag. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `layout` | — | none | Stream payload layout as a list of (name, width) fields; defaults to the I/Q layout of ``data_width`` samples. When a custom layout is given, data_width is ignored. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `status` (read-only, 17 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `level` | `0` | Current FIFO occupancy. |
| `[16]` | `overflow` | `0` | A sample was dropped (sticky). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 32 | 14 | 0 | 0 | 231.8 | — |
| xilinx | 40 | 14 | 0 | 0 | — | — |
| xilinx_au | 36 | 14 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
