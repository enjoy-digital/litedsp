# Clutter map

`LiteDSPClutterMap` — `litedsp.radar.clutter` — category `radar`

latency: 4 samples · CSR: yes · bypass: no

## Overview

Scan-to-scan clutter map detector on framed cell streams.

Keeps one exponential average per cell (``n_range_bins * n_doppler_bins`` cells, addressed
by a counter that ``first`` restarts) in a RAM holding ``sum = average << avg_shift``:
``sum += x - (sum >> avg_shift)`` on every scan unless the cell detects (censored update,
overridden by ``learn_all``) or ``freeze`` is set. The scan after
reset or ``clear`` (up to its ``last``)
initialises the visited cells (``sum = x << avg_shift``, no detection); scans must cover every
cell. ``threshold =
rounded(sum * alpha, threshold_frac + avg_shift)`` saturated and floored at ``threshold_min``,
``detect = x > threshold``. Output on :func:`~litedsp.common.cell_layout`; latency 4.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_range_bins` | `64` | int |  |
| `n_doppler_bins` | `1` | int |  |
| `data_width` | `17` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `avg_shift` | `3` | int |  |
| `alpha_width` | `16` | int |  |
| `threshold_frac` | `8` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | cell |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `alpha` (read-write, 16 bits, reset `0x400`)

Threshold factor on the cell's clutter average (unsigned Q.8).

### `threshold_min` (read-write, 17 bits)

Threshold floor (unsigned cell units).

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `learn_all` | `0` | Update the map with detected cells too. |
| `[1]` | `freeze` | `0` | Stop updating the map. |
| `[2]` | `clear` | `0` | Invalidate the map (re-learned on the next scan). (pulse) |

### `config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[19:0]` | `n_cells` | `0` | Map cells. |
| `[23:20]` | `avg_shift` | `0` | Averaging time constant (scans = 2^avg_shift). |
| `[31:24]` | `frac` | `0` | Fractional bits of alpha. |

### `detections` (read-only, 32 bits)

Detections since reset.

### `scans` (read-only, 32 bits)

Scans (frames) since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 554 | 294 | 0 | 2 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
