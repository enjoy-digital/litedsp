# Frame histogram

`LiteDSPPixelHistogram` — `litedsp.image.histogram` — category `image`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Histogram of one channel per frame into ``2**bins_log2`` bins (the code's top bits).

Counts accumulate in a ping-pong RAM at one pixel per clock (read-modify-write with a
same-bin forwarding register); ``last`` seals a bank and the block streams its bins out
(``data`` = count, ``first`` on bin 0, ``last`` on the final bin, one beat per bin) while
clearing them for reuse. A frame ending before the previous histogram drained sets the
sticky ``overrun``. ``max_pixels`` sizes the counts. ``latency = None``; one output beat
per bin per frame.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `1` | int | Choices: `1`, `3`. |
| `channel` | `0` | int |  |
| `bins_log2` | `8` | int | Choices: `4`, `5`, `6`, `7`, `8`. |
| `max_pixels` | `2073600` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 5 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `channel` | `0` | Measured channel. |
| `[4]` | `clear` | `0` | Clear the overrun flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `overrun` | `0` | Sticky: a frame ended before the previous histogram drained. |

### `config` (read-only, 4 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `bins_log2` | `0` | log2 of the bin count. |

### `frames` (read-only, 32 bits)

Frames counted.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 31128 | 10879 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
