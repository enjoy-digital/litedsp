# Crop (ROI)

`LiteDSPCrop` — `litedsp.image.scale` — category `image`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Pass a rectangular region of interest, consume everything else.

The ROI (``x0``, ``y0``, ``roi_width``, ``roi_height``) is shadowed and committed at the next
accepted ``first``; the output is re-framed (``first`` / ``eol`` / ``last`` from the ROI
corners). A ROI that extends beyond the learned frame sets the sticky ``geometry_error``.
Rate changer; latency 1.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `3` | int | Choices: `1`, `3`. |
| `x0` | `0` | int |  |
| `y0` | `0` | int |  |
| `roi_width` | `32` | int |  |
| `roi_height` | `24` | int |  |
| `coord_bits` | `12` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel_rgb |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `origin` (read-write, 28 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `x0` | `0` | ROI left column. |
| `[27:16]` | `y0` | `0` | ROI top row. |

### `size` (read-write, 28 bits, reset `0x180020`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `width` | `32` | ROI width. |
| `[27:16]` | `height` | `24` | ROI height. |

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit` | `0` | Apply the ROI at the next frame start. (pulse) |
| `[1]` | `clear` | `0` | Clear the geometry error. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit_pending` | `0` | A ROI change waits for the next frame. |
| `[1]` | `geometry_error` | `0` | Sticky: the ROI exceeded the frame. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 342 | 102 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
