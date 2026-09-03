# Alpha-beta tracker

`LiteDSPAlphaBetaTracker` — `litedsp.radar.track` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Alpha-beta tracker over ``n_tracks`` slots fed by per-CPI target bursts.

Each incoming record (:func:`~litedsp.common.target_layout`) is associated serially with
the active, not yet assigned track whose prediction lies within the gates
(``|dr| <= gate_r`` and ``|dd| <= gate_d``) with the lowest ``|dr| + |dd|`` (lowest index on
ties); an unassociated record initialises the lowest free slot (tentative, velocity 0) or is
dropped when none is free (``n_tracks + 2`` cycles per record, input stalled). The terminator
updates every active track: assigned tracks filter ``P = pred + alpha*e``,
``V = V + beta*e`` (gains unsigned Q1.gain_frac, positions Q.velocity_frac bins, velocities
Q.velocity_frac bins per CPI), count a hit and confirm at ``confirm_hits``; unassigned
tracks coast on their prediction and are freed after ``max_misses`` consecutive misses;
then ``pred = P + V``. The confirmed tracks (and the tentative ones with ``emit_tentative``)
are emitted as a :func:`~litedsp.common.track_layout` burst closed by a terminator whose
``hits`` field is the active track count; ``ev.update`` fires with it.
``latency = None``; rate data dependent.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_tracks` | `4` | int |  |
| `index_width` | `12` | int |  |
| `frac_bits` | `4` | int | Fractional bits of the coefficient/control fixed-point format. |
| `velocity_frac` | `8` | int |  |
| `gain_frac` | `8` | int |  |
| `data_width` | `17` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | target |
| `source` | source | track |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `gains` (read-write, 25 bits, reset `0x260080`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[8:0]` | `alpha` | `128` | Position gain (Q1.8). |
| `[24:16]` | `beta` | `38` | Velocity gain (Q1.8). |

### `gates` (read-write, 32 bits, reset `0x200020`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `range` | `32` | Range gate (Q.4 bins). |
| `[31:16]` | `doppler` | `32` | Doppler gate (Q.4 bins). |

### `control` (read-write, 10 bits, reset `0x23`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `confirm_hits` | `3` | Hits to confirm a track. |
| `[7:4]` | `max_misses` | `2` | Consecutive misses before a track is freed. |
| `[8]` | `emit_tentative` | `0` | Also emit tentative tracks. |
| `[9]` | `clear` | `0` | Free every track. (pulse) |

### `status` (read-only, 13 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `active` | `0` | Active tracks after the last update. |
| `[12:8]` | `confirmed` | `0` | Confirmed tracks after the last update. |

### `config` (read-only, 20 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `n_tracks` | `0` | Track slots. |
| `[11:8]` | `frac_bits` | `0` | Sub-bin fractional bits. |
| `[15:12]` | `velocity_frac` | `0` | Velocity fractional bits. |
| `[19:16]` | `gain_frac` | `0` | Gain fractional bits. |

### `dropped` (read-only, 32 bits)

Records dropped (no free slot).

### `cpi_count` (read-only, 32 bits)

Updates since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 2474 | 981 | 0 | 8 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
