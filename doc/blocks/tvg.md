# Time-varying gain

`LiteDSPTVG` — `litedsp.radar.sonar` — category `radar`

latency: 6 samples · CSR: yes · bypass: yes

## Overview

Time-varying gain: a log-domain gain ramp along the range bins of each frame.

The gain in log2 units (Q.gain_frac) is ``g(r) = g0 + k_log * log2(r) + k_lin * r`` for
range bin ``r`` (a counter restarted by ``first``; ``log2(r)`` from a ROM), clamped to
``[-2**max_gain_log2, 2**max_gain_log2)``, turned into a linear gain by
:class:`LiteDSPExp2` (Q.14) and applied as ``y = scaled(x * gain, 14, data_width)`` with the
sticky ``saturated`` flag. The sample rides a matching-latency
:class:`LiteDSPDelay` branch behind a :class:`LiteDSPSplit`, so ``bypass`` is an exact
same-latency passthrough. ``litedsp.radar.design.tvg_coefficients`` gives the words for a
``db_per_decade * log10(r) + alpha * r + g0`` law (40 dB/decade = two-way spherical
spreading). Latency 6.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_range_bins` | `1024` | int |  |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `gain_frac` | `8` | int |  |
| `max_gain_log2` | `8` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `g0` (read-write, 17 bits)

Log2 gain at bin 0 (signed Q.8).

### `k_log` (read-write, 17 bits)

Log2 gain per log2(range bin).

### `k_lin` (read-write, 17 bits)

Log2 gain per range bin.

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `bypass` | `0` | Pass the samples unchanged (same latency). |
| `[1]` | `clear` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturated` | `0` | Sticky: an output saturated. |

### `config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `gain_frac` | `0` | Log2 gain fractional bits. |
| `[7:4]` | `max_gain_log2` | `0` | Gain clamp (2^max_gain_log2). |
| `[23:8]` | `n_range_bins` | `0` | Range bins per frame. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 896 | 374 | 2 | 6 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
