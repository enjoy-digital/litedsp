# Stereo matrix (M/S, pan)

`LiteDSPStereoMatrix` — `litedsp.audio.level` — category `audio`

latency: 4 samples · CSR: yes · bypass: yes

## Overview

2x2 matrix on a stereo TDM stream: ``L' = a*L + b*R``, ``R' = c*L + d*R``.

Mid/side encode (``a = b = c = 0.5, d = -0.5``) and decode (``1, 1, 1, -1``),
constant-power panning, width control, channel swap or mono fold-down are all coefficient
presets (see ``StereoMatrixDriver``). Coefficients are signed Q3.``coeff_frac``; each output
is rounded once and saturated (sticky ``sat``). A serial engine accepts the L beat (channel
0) then the R beat, computes the four products on one multiplier and emits the two output
beats; beats arriving out of order set the sticky ``sequence_error`` and are dropped.
``cycles_per_frame = 8``; ``bypass`` passes beats through (latency 1).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coeff_width` | `18` | int | Width of the signed coefficients. |
| `coeff_frac` | `15` | int | Fractional bits of the coefficients (1.0 = 2**coeff_frac, must be < coeff_width - 1). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `a` (read-write, 18 bits, reset `0x8000`)

Matrix coefficient a (signed Q3.15).

### `b` (read-write, 18 bits)

Matrix coefficient b (signed Q3.15).

### `c` (read-write, 18 bits)

Matrix coefficient c (signed Q3.15).

### `d` (read-write, 18 bits, reset `0x8000`)

Matrix coefficient d (signed Q3.15).

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `bypass` | `0` | Pass beats through unchanged. |
| `[1]` | `clear_sat` | `0` | Clear saturation / sequence flags. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturation` | `0` | An output saturated since the last clear. |
| `[1]` | `sequence_error` | `0` | A beat arrived out of L/R order. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 617 | 171 | 0 | 2 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
