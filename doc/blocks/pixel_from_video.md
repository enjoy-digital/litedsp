# Pixels from LiteX video

`LiteDSPPixelFromVideo` — `litedsp.image.video` — category `image`

latency: 1 sample · CSR: yes · bypass: no

## Overview

LiteX ``video_data_layout`` stream to a framed RGB pixel stream.

Blanking beats (``de = 0``) are consumed unconditionally; active pixels are framed from the
syncs: the column restarts on the rising edge of ``de``, the row on the rising edge of
``vsync``, ``first`` marks the first active pixel after a vsync, ``eol`` the pixel at
``width - 1`` and ``last`` the ``eol`` of row ``height - 1`` (runtime geometry CSRs). A line
shorter or longer than ``width`` sets the sticky ``geometry_error``. Latency 1.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `width` | `64` | int |  |
| `height` | `48` | int |  |
| `coord_bits` | `12` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | video |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `geometry` (read-write, 28 bits, reset `0x300040`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `width` | `64` | Active pixels per line. |
| `[27:16]` | `height` | `48` | Active lines per frame. |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the geometry error. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `geometry_error` | `0` | Sticky: a line did not match the width. |

### `frames` (read-only, 32 bits)

Frames received.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 258 | 89 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
