# Sobel edge magnitude

`LiteDSPSobel` — `litedsp.image.edge` — category `image`

latency: 72 samples · CSR: yes · bypass: yes

## Overview

Sobel edge magnitude on a mono raster stream.

``gx`` and ``gy`` (adders only) come from a 3x3 :class:`LiteDSPLineBuffer` window; the
runtime ``mode`` picks the magnitude ``|gx| + |gy|`` (L1), ``max(|gx|, |gy|)`` (L-inf) or
``max + min/4`` (alpha-max-beta-min), then ``clamped(rounded(mag, shift))`` (``shift = 3``
maps the L1 maximum ``8 * full`` onto the code range). With ``with_direction`` a 2-bit
``direction`` field (0 horizontal edge, 1 = 45 degrees, 2 vertical, 3 = 135 degrees, quantised
with tan 22.5 = 53/128) is added. ``bypass`` outputs the window centre. Latency
``line_buffer.latency + 3``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `width` | `64` | int |  |
| `max_width` | — | none |  |
| `border` | `"replicate"` | str | Choices: `replicate`, `mirror`, `zero`. |
| `mode` | `"l1"` | str | Choices: `l1`, `linf`, `approx`. |
| `shift` | `3` | int | Output rescale shift (defaults to data_width - 1). |
| `with_direction` | `False` | bool |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel |
| `source` | source | pixel |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 10 bits, reset `0x30`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `mode` | `0` | 0 L1, 1 L-inf, 2 alpha-max-beta-min. |
| `[6:4]` | `shift` | `3` | Right shift of the magnitude. |
| `[8]` | `bypass` | `0` | Pass the window centre (same latency). |
| `[9]` | `clear` | `0` | Clear the geometry error. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `geometry_error` | `0` | Sticky: line length changed or exceeded max_width. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1163 | 372 | 2 | 1 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
