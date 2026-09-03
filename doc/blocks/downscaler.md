# Box downscaler

`LiteDSPDownscaler` — `litedsp.image.scale` — category `image`

latency: 2 samples · CSR: yes · bypass: no

## Overview

Exact box-mean downscaling by ``decimation`` (2, 4 or 8) in both directions.

Pixels accumulate horizontally over ``decimation`` columns, the partial sums accumulate
vertically in a RAM indexed by the tile column (``max_width / decimation`` deep), and each
tile emits ``rounded(sum, 2 log2 D)`` on its last row and column. Partial tiles at the right
and bottom edges are dropped; the output is framed from the tile counters and the runtime
``width`` / ``height`` (``eol`` at the last full tile column, ``last`` on the last full tile
row). Rate changer (one output per ``D^2`` inputs); latency 2 from the tile's last pixel.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `1` | int | Choices: `1`, `3`. |
| `decimation` | `2` | int | Integer decimation factor. Choices: `2`, `4`, `8`. |
| `width` | `64` | int |  |
| `height` | `48` | int |  |
| `max_width` | — | none |  |
| `coord_bits` | `12` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel |
| `source` | source | pixel |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `geometry` (read-write, 28 bits, reset `0x300040`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `width` | `64` | Input pixels per line. |
| `[27:16]` | `height` | `48` | Input lines per frame. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 339 | 172 | 1 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
