# Pixel pattern source

`LiteDSPPixelPattern` — `litedsp.image.pattern` — category `image`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Framed raster test-pattern source (``pixel_layout``), geometry from CSRs.

Runtime ``mode``: ``const`` (``const_r/g/b``), ``ramp`` (``r = x``, ``g = y``, ``b = x + y``
modulo the code range; mono: ``x``), ``bars`` (eight LiteX-order colour bars, the last bar
absorbs the remainder of ``width``), ``checker`` (8 x 8 full-scale checks), ``counter``
(the pixel index within the frame on every channel) and ``bayer`` (the colour bars sampled
on an RGGB mosaic, one channel). ``enable`` streams frames back to back, ``trigger`` sends
one frame; ``width`` / ``height`` are runtime (reset to the build values). Status: ``busy``
and the frame count. Source-only, one pixel per cycle.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `3` | int | Choices: `1`, `3`. |
| `width` | `64` | int |  |
| `height` | `48` | int |  |
| `mode` | `"bars"` | str | Choices: `const`, `ramp`, `bars`, `checker`, `counter`, `bayer`. |
| `coord_bits` | `12` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 7 bits, reset `0x20`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `enable` | `0` | Stream frames continuously. |
| `[1]` | `trigger` | `0` | Send one frame. (pulse) |
| `[6:4]` | `mode` | `2` | 0 const, 1 ramp, 2 bars, 3 checker, 4 counter, 5 bayer. |

### `geometry` (read-write, 28 bits, reset `0x300040`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `width` | `64` | Pixels per line. |
| `[27:16]` | `height` | `48` | Lines per frame. |

### `const` (read-write, 24 bits, reset `0xffffff`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `r` | `255` | Constant red / mono value. |
| `[15:8]` | `g` | `255` | Constant green. |
| `[23:16]` | `b` | `255` | Constant blue. |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `busy` | `0` | A frame is being sent. |

### `frames` (read-only, 32 bits)

Frames sent since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 538 | 108 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
