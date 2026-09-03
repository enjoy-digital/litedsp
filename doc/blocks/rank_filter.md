# Rank filter (median)

`LiteDSPRankFilter` — `litedsp.image.rank` — category `image`

latency: 73 samples · CSR: yes · bypass: yes

## Overview

Rank-order filter on a 3x3 neighbourhood (per channel).

A 36-comparator odd-even transposition network (three pipeline registers) orders the nine
window pixels;
the runtime ``rank`` (0 = erosion / minimum, 4 = median, 8 = dilation / maximum) selects the
output. ``bypass`` outputs the window centre. Latency ``line_buffer.latency + 4``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `1` | int | Choices: `1`, `3`. |
| `rank` | `4` | int |  |
| `width` | `64` | int |  |
| `max_width` | — | none |  |
| `border` | `"replicate"` | str | Choices: `replicate`, `mirror`, `zero`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel |
| `source` | source | pixel |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 6 bits, reset `0x4`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `rank` | `4` | 0 erode (min), 4 median, 8 dilate (max). |
| `[4]` | `bypass` | `0` | Pass the window centre (same latency). |
| `[5]` | `clear` | `0` | Clear the geometry error. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `geometry_error` | `0` | Sticky: line length changed or exceeded max_width. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1741 | 559 | 2 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
