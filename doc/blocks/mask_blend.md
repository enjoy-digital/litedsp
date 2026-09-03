# Mask blend

`LiteDSPAlphaBlend` — `litedsp.image.blend` — category `image`

latency: 1 sample · CSR: yes · bypass: no

## Overview

``y = rounded(a * A + (256 - a) * B, 8)`` per channel over two lock-stepped pixel streams.

``sink_a`` and ``sink_b`` (and the mono ``sink_alpha`` with ``with_alpha_sink``, its full
scale mapping to 256) are joined; the framing comes from ``sink_a``. ``alpha`` is a 9-bit
runtime value (256 = 1.0) when no alpha stream is used. Latency 1.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `3` | int | Choices: `1`, `3`. |
| `alpha` | `128` | int |  |
| `with_alpha_sink` | `True` | bool |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink_a` | sink | pixel_rgb |
| `sink_alpha` | sink | pixel |
| `sink_b` | sink | pixel_rgb |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `alpha` (read-write, 9 bits, reset `0x80`)

Blend factor (256 = 1.0, unused with an alpha stream).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
