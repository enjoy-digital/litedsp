# Pixel FIFO

`LiteDSPPixelFIFO` — `litedsp.image.stream` — category `image`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Elastic buffer for a pixel stream (``pixel_layout``, tags carried).

A thin wrapper over :class:`LiteDSPStreamFIFO` with the pixel layout: the buffer a parallel
branch needs to run at least ``kernel.latency`` beats ahead of a 2-D block before a
lock-step join (a line-buffer branch delays by ``P * width`` beats). Exposes ``level`` and the
sticky ``overflow`` flag; latency 0 (first-word fall-through).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `depth` | `256` | int |  |
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `3` | int | Choices: `1`, `3`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel_rgb |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `level` (read-only, 9 bits)

Pixels buffered.

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `overflow` | `0` | Sticky: a pixel was dropped (sink stalled). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 695 | 26 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
