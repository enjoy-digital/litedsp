# 2-D CA-CFAR detector

`LiteDSPCFAR2D` — `litedsp.radar.cfar_2d` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Cell-averaging CFAR over a ``(2R+1) x (2C+1)`` box of a range-Doppler map.

The map arrives as ``n_range_bins`` frames (rows) of ``n_doppler_bins`` cells (the corner
turn / Doppler processor order, rows counted from reset); ``R = n_train[0] + n_guard[0]``
rows and ``C = n_train[1] + n_guard[1]`` cells on each side of the cell under test form the
box, the inner ``(2*n_guard[0]+1) x (2*n_guard[1]+1)`` guard box is excluded, so the
training sum spans ``n_training = box - guard`` cells. The last ``2R+1`` rows live in a line
buffer (one write and four read ports: the row leaving the box, the rows entering and
leaving the guard box and the centre row; the RAM is replicated by synthesis), the vertical
column sums of both boxes are kept in two ``n_doppler_bins``-entry RAMs and slide by one row
per incoming row, and a ``2C+1``-wide shift register slides horizontally. Edges are zero
padded: ``C`` virtual cells after each row and ``R`` virtual rows after each CPI are flushed
with ``sink.ready`` low, so the output has one cell per input cell in the same order and
framing (throughput ``M / (M + C)``). Threshold ``sum * alpha * round(2**16 / n_training)``
rounded and saturated, ``alpha`` unsigned Q(alpha_width - threshold_frac).threshold_frac
(see ``litedsp.radar.design.cfar_alpha``). A ``first``/``last`` at the wrong position sets
the sticky ``frame_error`` and re-synchronises the row. ``latency = None``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_range_bins` | `64` | int |  |
| `n_doppler_bins` | `16` | int |  |
| `n_train` | `(4, 2)` | list |  |
| `n_guard` | `(1, 1)` | list |  |
| `data_width` | `17` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `alpha_width` | `16` | int |  |
| `threshold_frac` | `8` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | cell |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `alpha` (read-write, 16 bits, reset `0x200`)

Threshold factor on the training mean (unsigned Q.8).

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the frame error. (pulse) |

### `config` (read-only, 25 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `n_training` | `0` | Training cells in the box. |
| `[23:16]` | `frac` | `0` | Fractional bits of alpha. |
| `[24]` | `two_d` | `0` | 1: n_training is the 2-D box count. |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `frame_error` | `0` | Sticky: row framing did not match n_doppler_bins. |

### `detections` (read-only, 32 bits)

Detections since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1321 | 723 | 4 | 5 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_cfar_2d.py` (bit-exact/SNR under randomized backpressure).
