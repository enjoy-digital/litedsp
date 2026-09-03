# Pixel gain / offset

`LiteDSPPixelGain` — `litedsp.image.point` — category `image`

latency: 2 samples · CSR: yes · bypass: yes

## Overview

Per-channel gain and offset: ``y = clamped(rounded(x * gain, gain_frac) + offset)``.

Gains are unsigned Q4.gain_frac (reset 1.0), offsets signed ``data_width + 1`` bits; the
products are registered, the sticky ``sat`` flags a clamp. White balance, brightness and
contrast in one block (see ``PixelGainDriver``). ``bypass``. Latency 2.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `3` | int | Choices: `1`, `3`. |
| `gain_frac` | `8` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel_rgb |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `gain0` (read-write, 25 bits, reset `0x100`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `gain` | `256` | Channel 0 gain (unsigned Q4.8). |
| `[24:16]` | `offset` | `0` | Channel 0 offset (signed). |

### `gain1` (read-write, 25 bits, reset `0x100`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `gain` | `256` | Channel 1 gain (unsigned Q4.8). |
| `[24:16]` | `offset` | `0` | Channel 1 offset (signed). |

### `gain2` (read-write, 25 bits, reset `0x100`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `gain` | `256` | Channel 2 gain (unsigned Q4.8). |
| `[24:16]` | `offset` | `0` | Channel 2 offset (signed). |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `sat` | `0` | Sticky: an output clamped. |

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 158 | 97 | 0 | 3 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
