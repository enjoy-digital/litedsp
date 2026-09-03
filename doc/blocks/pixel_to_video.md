# Pixels to LiteX video

`LiteDSPPixelToVideo` — `litedsp.image.video` — category `image`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Framed RGB pixels onto a LiteX timing-generator stream (``video_timing_layout``) as a
``video_data_layout`` stream.

``vtg_sink`` paces the output: every timing beat produces one video beat (blanking beats
carry black), each active (``de``) beat pulls one pixel from ``sink``. The FSM starts in SYNC
(black output, stale pixels dropped and counted until the timing stream's frame start meets
a ``first`` pixel) and runs from there; an active beat without a pixel outputs black, sets the
sticky ``underflow`` and counts it (optional ``ev.underflow``); ``first`` arriving elsewhere
than at a frame start re-synchronises. Latency 1 (timing beat to video beat); the pixel
rate follows the timing (cosim excluded).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coord_bits` | `12` | int |  |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel_rgb |
| `source` | source | video |
| `vtg_sink` | sink | raw |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the underflow flag. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `underflow` | `0` | Sticky: an active beat had no pixel. |
| `[1]` | `synced` | `0` | Pixels are locked to the timing. |

### `underflows` (read-only, 32 bits)

Active beats without a pixel.

### `dropped` (read-only, 32 bits)

Pixels dropped while synchronising.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 109 | 94 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
