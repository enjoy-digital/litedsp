# Frame statistics tap

`LiteDSPPixelStats` — `litedsp.image.stats` — category `image`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Zero-latency passthrough that measures one channel per frame.

``sum``, ``min``, ``max`` and ``count`` over the frame plus ``zones x zones`` zone sums (zone
index from the pixel coordinates against the runtime ``zone_width`` / ``zone_height``,
clamped to the last zone) accumulate on the selected channel and are latched at ``last``
(``update`` pulse, optional ``ev.frame`` interrupt); the mean is host-side. ``max_pixels``
sizes the accumulators. Latency 0 (``sink`` connects to ``source``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `1` | int | Choices: `1`, `3`. |
| `channel` | `0` | int |  |
| `zones` | `4` | int | Choices: `1`, `2`, `4`, `8`. |
| `max_pixels` | `2073600` | int |  |
| `coord_bits` | `12` | int |  |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel |
| `source` | source | pixel |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `channel` | `0` | Measured channel. |

### `zone_size` (read-write, 32 bits, reset `0x7800a0`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `width` | `160` | Zone width (pixels). |
| `[31:16]` | `height` | `120` | Zone height (lines). |

### `sum` (read-only, 29 bits)

Frame sum of the channel.

### `minmax` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `min` | `0` | Frame minimum. |
| `[23:16]` | `max` | `0` | Frame maximum. |

### `count` (read-only, 21 bits)

Pixels in the frame.

### `zone_index` (read-write, 4 bits)

Zone to read.

### `zone_sum` (read-only, 29 bits)

Sum of the selected zone.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1771 | 1101 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
