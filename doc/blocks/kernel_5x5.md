# 2-D kernel (5x5)

`LiteDSPKernel2D` — `litedsp.image.kernel` — category `image`

latency: 139 samples · CSR: yes · bypass: yes

## Overview

``kernel_size x kernel_size`` correlation kernel on a raster stream (per channel).

A :class:`LiteDSPLineBuffer` supplies the neighbourhood; each channel computes
``sum(coef[i][j] * w[i][j])`` with signed ``coeff_width`` coefficients (row-major, ``coef[0][0]``
on the top-left neighbour), then ``y = clamped(rounded(acc, shift) + offset)`` with the sticky
``sat`` flag. Coefficients live in shadow registers loaded through ``coeff_index`` (auto-
incremented by a ``coeff_we`` write) and copied to the active set by ``commit`` at the next
accepted ``first`` (frame-atomic, ``commit_pending`` meanwhile) or immediately by
``commit_now``; ``shift`` (0..15) and the signed ``offset`` are runtime. ``bypass`` outputs the
window centre at the same latency. Presets from ``litedsp.image.design.kernel_preset``.
``latency = line_buffer.latency + 2``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `1` | int | Choices: `1`, `3`. |
| `kernel_size` | `5` | int |  |
| `coefficients` | `[1, 4, 6, 4, 1, 4, 16, 24, 16, 4, 6, 24, 36, 24, 6, 4, 16, 24, 16, 4, 1, 4, 6, 4, 1]` | list | Coefficient list (signed integers, quantized via litedsp.filter.design). |
| `coeff_width` | `10` | int |  |
| `shift` | `8` | int | Output rescale shift (defaults to data_width - 1). |
| `offset` | `0` | int |  |
| `width` | `64` | int |  |
| `max_width` | — | none |  |
| `border` | `"replicate"` | str | Choices: `replicate`, `mirror`, `zero`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel |
| `source` | source | pixel |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `coeff_index` (read-write, 5 bits)

Shadow coefficient index (auto-increments on a value write).

### `coeff_value` (read-write, 10 bits)

Writing loads the shadow coefficient at coeff_index (signed).

### `shift_offset` (read-write, 17 bits, reset `0x8`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `shift` | `8` | Right shift of the sum. |
| `[16:8]` | `offset` | `0` | Signed offset added after the shift. |

### `control` (read-write, 5 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit` | `0` | Copy the shadow set at the next frame start. (pulse) |
| `[1]` | `commit_now` | `0` | Copy the shadow set immediately. (pulse) |
| `[2]` | `bypass` | `0` | Pass the window centre (same latency). |
| `[3]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |
| `[4]` | `clear` | `0` | Clear the geometry error. (pulse) |

### `status` (read-only, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit_pending` | `0` | A commit waits for the next frame start. |
| `[1]` | `sat` | `0` | Sticky: an output clamped. |
| `[2]` | `geometry_error` | `0` | Sticky: line length changed or exceeded max_width. |

### `config` (read-only, 18 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `kernel_size` | `0` | Kernel size. |
| `[12:8]` | `coeff_width` | `0` | Coefficient width. |
| `[17:16]` | `n_channels` | `0` | Channels. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 3571 | 1575 | 4 | 25 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
