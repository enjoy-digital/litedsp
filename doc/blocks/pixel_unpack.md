# Pixel unpack

`LiteDSPPixelUnpack` — `litedsp.image.adapt` — category `image`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Unpack memory words back into pixels (inverse of :class:`LiteDSPPixelPack`; ``rgb565``
zero-fills the low bits) and regenerate ``eol`` from a column counter against the runtime
``width`` (``first`` restarts it). Latency 1.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `format` | `"rgb888"` | str | Choices: `rgb888`, `xrgb8888`, `rgb565`, `mono`. |
| `width` | `64` | int |  |
| `coord_bits` | `12` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `width` (read-write, 12 bits, reset `0x40`)

Pixels per line (eol regeneration).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 66 | 40 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_adapt.py` (bit-exact/SNR under randomized backpressure).
