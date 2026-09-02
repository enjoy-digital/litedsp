# Dither / requantizer

`LiteDSPDither` — `litedsp.audio.dither` — category `audio`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Word-length reduction with TPDF dither and optional error-feedback noise shaping.

Requantizes ``data_width`` samples to ``out_width`` bits (the result stays MSB-aligned in
the ``data_width`` output word, low bits zero): triangular-PDF dither of +/-1 output LSB
from two independent xorshift32 generators decorrelates the quantization error from the
signal (no harmonic distortion at low levels), and error feedback of the previous
requantization error(s) -- measured against the undithered input so the dither noise is
shaped as well -- moves the noise away from the low frequencies (``"ef1"``: ``v = x +
e[n-1]``, noise transfer 1 - z^-1; ``"ef2"``: ``v = x + 2e[n-1] - e[n-2]``, (1 - z^-1)^2),
per channel of the TDM stream. ``dither_enable``/``shaping_enable`` are
runtime switches; saturation is sticky. Latency 1, no multiplier.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `out_width` | `16` | int | Output word length in bits (< data_width; e.g. 24 -> 16). |
| `n_channels` | `2` | int | Channels in the TDM frame (per-channel error state). |
| `shaping` | `"none"` | str | Error-feedback structure built: ``"none"``, ``"ef1"`` or ``"ef2"``. Choices: `none`, `ef1`, `ef2`. |
| `seed` | `625341585` | int | Seed of the dither generators (must be non-zero). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 3 bits, reset `0x1`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `dither_enable` | `1` | Add TPDF dither. |
| `[1]` | `shaping_enable` | `0` | Enable the error-feedback noise shaping. |
| `[2]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturation` | `0` | Output saturated since the last clear. |

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 285 | 133 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_dither.py` (bit-exact/SNR under randomized backpressure).
