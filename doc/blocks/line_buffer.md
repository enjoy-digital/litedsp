# Line buffer (window)

`LiteDSPLineBuffer` — `litedsp.image.linebuffer` — category `image`

latency: 69 samples · CSR: yes · bypass: no

## Overview

Sliding ``kernel_size x kernel_size`` window over a raster pixel stream.

``kernel_size - 1`` line RAMs (``max_width`` deep) hold the previous lines; the incoming
pixel and the RAM reads form a column that shifts into the window registers, so output beat
k carries the neighbourhood of input pixel k (``w{row}{col}``, channels packed LSB-first,
``w{P}{P}`` = the pixel itself) with the same ``first`` / ``eol`` / ``last`` framing. Borders:
``replicate`` (edge pixel), ``mirror`` (``p[-1] = p[1]``, keeps a Bayer phase) or ``zero``;
they are applied by muxes on the output side from the output coordinates, the learned line
width and the frame height. ``P`` virtual beats after every line and ``P`` virtual lines
after the frame (``sink.ready`` low, ``P = kernel_size // 2``) push the trailing outputs out,
so the stream stays 1:1 with a throughput of ``width / (width + P)``. A line longer than
``max_width`` or a line length change inside a frame sets the sticky ``geometry_error``
(framing re-synchronises on ``first``). ``latency = P * (width + P) + P + 3`` at the build
width.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `1` | int | Choices: `1`, `3`. |
| `kernel_size` | `3` | int | Choices: `3`, `5`, `7`. |
| `width` | `64` | int |  |
| `max_width` | — | none |  |
| `border` | `"replicate"` | str | Choices: `replicate`, `mirror`, `zero`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel |
| `source` | source | raw |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the geometry error. (pulse) |

### `status` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `geometry_error` | `0` | Sticky: line length changed or exceeded max_width. |
| `[31:16]` | `line_length` | `0` | Learned line length. |

### `config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `kernel_size` | `0` | Window size. |
| `[23:8]` | `max_width` | `0` | Line RAM depth. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1340 | 295 | 2 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
