# Pixel pack

`LiteDSPPixelPack` — `litedsp.image.adapt` — category `image`

latency: 0 samples · CSR: no · bypass: no

## Overview

Pack pixels into memory words: ``rgb888`` (``r`` in the low byte, then ``g``, ``b``),
``xrgb8888`` (little-endian XRGB: ``b`` low byte, ``g``, ``r``, zero), ``rgb565`` and
``mono``. Combinational (latency 0); ``eol`` is dropped, ``first`` / ``last`` kept.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `format` | `"rgb888"` | str | Choices: `rgb888`, `xrgb8888`, `rgb565`, `mono`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel_rgb |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 0 | 0 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_adapt.py` (bit-exact/SNR under randomized backpressure).
