# Kalman tracker

`LiteDSPKalmanTracker` — `litedsp.radar.kalman` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Constant-velocity Kalman tracker over ``n_tracks`` slots (same stream contract, association,
confirmation and emission as :class:`LiteDSPAlphaBetaTracker`).

Per track and axis the filter keeps the covariance ``P11, P12, P22`` (Q.cov_frac, clamped to
``cov_width`` bits with the sticky ``cov_sat``). On the terminator each active track first
predicts its covariance with the process noise ``q`` (``P11 += 2 P12 + P22 + q/4``,
``P12 += P22 + q/2``, ``P22 += q``), then, when assigned, computes the gains
``K1 = P11 / (P11 + r)`` and ``K2 = P12 / (P11 + r)`` with bit-serial dividers
(``cov_width + cov_frac`` cycles, both axes in parallel), updates ``P = pred + K1 e``,
``V = V + K2 e`` and the covariance (``P11 (1 - K1)``, ``P12 (1 - K1)``,
``P22 - K2 P12``); coasting tracks keep the predicted covariance. New tracks start with
``P11 = r``, ``P12 = 0``, ``P22 = p_vel0``. ``q``, ``r`` and ``p_vel0`` are runtime
(Q.cov_frac, bins^2 and bins^2 per CPI^2); for a tracking index ``lam = sqrt(q / r)`` the
steady-state gains approach ``alpha_beta_from_index(lam)``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_tracks` | `4` | int |  |
| `index_width` | `12` | int |  |
| `frac_bits` | `4` | int | Fractional bits of the coefficient/control fixed-point format. |
| `velocity_frac` | `8` | int |  |
| `cov_frac` | `8` | int |  |
| `cov_width` | `24` | int |  |
| `data_width` | `17` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | target |
| `source` | source | track |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `noise` (read-write, 32 bits, reset `0x80000d`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `q` | `13` | Process noise (Q.8 bins^2/CPI^2). |
| `[31:16]` | `r` | `128` | Measurement noise (Q.8 bins^2). |

### `p_vel0` (read-write, 24 bits, reset `0x400`)

Initial velocity variance.

### `cov` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear_sat` | `0` | Clear the covariance saturation flag. (pulse) |

### `cov_status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `cov_sat` | `0` | Sticky: a covariance term saturated. |

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
| ecp5 | 5884 | 1940 | 0 | 20 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_kalman.py` (bit-exact/SNR under randomized backpressure).
