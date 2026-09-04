# Box overlay

`LiteDSPBoxOverlay` — `litedsp.image.overlay` — category `image`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Draw up to ``n_boxes`` rectangle outlines on a pixel stream.

Each box (``x0``, ``y0``, ``x1``, ``y1`` inclusive corners, colour, enable) lives in a shadow
table written through ``box_index`` and committed at the next accepted ``first``; the
runtime ``thickness`` (1..15) sets the outline width and the lowest enabled box wins where
outlines overlap; ``boxes`` seeds both tables at build time. Coordinates come from a
:class:`LiteDSPPixelCounter`. ``bypass``;
latency 1.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `3` | int | Choices: `1`, `3`. |
| `n_boxes` | `4` | int |  |
| `thickness` | `1` | int |  |
| `boxes` | — | none |  |
| `coord_bits` | `12` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel_rgb |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `box_index` (read-write, 2 bits)

Shadow box to write.

### `box_origin` (read-write, 28 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `x0` | `0` | Left column. |
| `[27:16]` | `y0` | `0` | Top row. |

### `box_corner` (read-write, 28 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `x1` | `0` | Right column (inclusive). |
| `[27:16]` | `y1` | `0` | Bottom row (inclusive). |

### `box_color` (read-write, 32 bits)

Writing stores the shadow box at box_index.

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[23:0]` | `color` | `0` | Outline colour (channels packed LSB-first). |
| `[31]` | `enable` | `0` | Box enabled. |

### `control` (read-write, 8 bits, reset `0x10`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit` | `0` | Apply the shadow table at the next frame start. (pulse) |
| `[7:4]` | `thickness` | `1` | Outline thickness (1..15). |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit_pending` | `0` | A commit waits for the next frame. |

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1145 | 637 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
