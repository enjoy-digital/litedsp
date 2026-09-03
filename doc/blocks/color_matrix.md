# Colour matrix

`LiteDSPColorMatrix` — `litedsp.image.color` — category `image`

latency: 3 samples · CSR: yes · bypass: yes

## Overview

``y_c = clamped(rounded(sum_k m[c][k] * (x_k - in_off_k), coeff_frac) + out_off_c)`` on RGB
pixels, three or one output channel.

Coefficients are signed Q(coeff_width - coeff_frac).coeff_frac (presets in
``litedsp.image.design.color_preset``: BT.601 / 709 studio, JPEG full range, grey, selects),
offsets in codes. The nine coefficients and six offsets live in a shadow table
(``coeff_index`` 0..8 coefficients row-major, 9..11 input offsets, 12..14 output offsets)
committed at the next accepted ``first`` or immediately. Sticky ``sat``; ``bypass`` when
``n_out == 3``. Latency 3.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_out` | `3` | int |  |
| `coefficients` | `[4096, 0, 0, 0, 4096, 0, 0, 0, 4096]` | list | Coefficient list (signed integers, quantized via litedsp.filter.design). |
| `in_offsets` | `(0, 0, 0)` | list |  |
| `out_offsets` | `(0, 0, 0)` | list |  |
| `coeff_width` | `16` | int |  |
| `coeff_frac` | `12` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel_rgb |
| `source` | source | pixel_rgb |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `coeff_index` (read-write, 4 bits)

Shadow index (0..8 matrix, 9..11 input offsets, 12..14 output offsets); auto-increments on a value write.

### `coeff_value` (read-write, 16 bits)

Writing stores the shadow entry at coeff_index (signed).

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit` | `0` | Copy the shadow set at the next frame start. (pulse) |
| `[1]` | `commit_now` | `0` | Copy the shadow set immediately. (pulse) |
| `[2]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit_pending` | `0` | A commit waits for the next frame start. |
| `[1]` | `sat` | `0` | Sticky: an output clamped. |

### `config` (read-only, 13 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `n_out` | `0` | Output channels. |
| `[12:8]` | `coeff_frac` | `0` | Coefficient fractional bits. |

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 742 | 950 | 0 | 9 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
