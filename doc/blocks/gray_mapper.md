# Gray mapper

`LiteDSPGrayMapper` — `litedsp.comm.gray` — category `comm`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Binary to Gray (``g = b ^ (b >> 1)``) on ``n_lanes`` words of ``width`` bits per beat, so
adjacent constellation points differ in one bit. Latency 1.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `width` | `2` | int |  |
| `n_lanes` | `1` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 12 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `width` | `0` | Bits per lane. |
| `[11:8]` | `n_lanes` | `0` | Lanes per beat. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 7 | 11 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
