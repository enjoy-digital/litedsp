# Gamma (LUT)

`LiteDSPPixelLUT` — `litedsp.image.lut` — category `image`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Code-to-code lookup on every channel (``2**data_width`` entries per table).

``shared`` uses one table for all channels (three read ports), otherwise one table per
channel; tables initialise to the ``gamma`` curve (1.0 = identity). The host rewrites
entries through ``lut_addr`` (auto-incremented by a ``lut_data`` write) with ``lut_channel``
(3 = all tables); loads may happen mid-frame. ``bypass``. Latency 1 (synchronous read).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `3` | int |  |
| `shared` | `True` | bool |  |
| `gamma` | `2.2` | float |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel_rgb |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `lut_addr` (read-write, 8 bits)

Table address (auto-increments on a data write).

### `lut_data` (read-write, 18 bits, reset `0x30000`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `data` | `0` | Writing stores the entry at lut_addr. |
| `[17:16]` | `channel` | `3` | Table 0..2, 3 = all. |

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
