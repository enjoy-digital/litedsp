# Debayer (bilinear)

`LiteDSPDebayer` — `litedsp.image.debayer` — category `image`

latency: 71 samples · CSR: yes · bypass: no

## Overview

Bilinear demosaic of a raw Bayer (mono) stream into RGB.

A 3x3 :class:`LiteDSPLineBuffer` (``mirror`` border by default, which keeps the colour phase
of the virtual pixels) feeds the interpolation; the colour site follows the output
coordinate parity (a :class:`LiteDSPPixelCounter` on the window stream) XOR the runtime
2-bit ``phase`` (row, column) for cropped sensors, starting from the build-time ``pattern``.
Red / blue sites take the centre, the mean of the four edge neighbours and of the four
corners; green sites take the centre and the two-pixel means along and across the row
(rounded half up). Latency ``line_buffer.latency + 2``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `pattern` | `"rggb"` | str | Choices: `rggb`, `bggr`, `grbg`, `gbrg`. |
| `width` | `64` | int |  |
| `max_width` | — | none |  |
| `border` | `"mirror"` | str | Choices: `mirror`, `replicate`, `zero`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 5 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `phase` | `0` | Flip the (col, row) colour phase (cropped sensors). |
| `[4]` | `clear` | `0` | Clear the geometry error. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `geometry_error` | `0` | Sticky: line length changed or exceeded max_width. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 905 | 376 | 2 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_debayer.py` (bit-exact/SNR under randomized backpressure).
