# Sigma-delta modulator

`LiteDSPSigmaDeltaModulator` — `litedsp.audio.pdm` — category `audio`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Error-feedback sigma-delta modulator: ``real_layout`` samples to a 1-bit stream at
``interpolation`` bits per sample (zero-order hold).

Per output bit with the held input ``x``: ``u = x + e1`` (order 1) or ``u = x + 2*e1 - e2``
(order 2); ``bit = (u >= 0)``; ``e = u - (bit ? +FS : -FS)`` with ``FS = 2**(data_width -
1)``, the error state saturated to ``data_width + 2`` bits. The quantization noise is shaped
by ``(1 - z**-1)**order``. Keep the input below about -3 dBFS for the second-order loop to
stay in its stable range. Latency 1 (first bit), rate ``(interpolation, 1)``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `interpolation` | `64` | int | Integer interpolation factor. |
| `order` | `2` | int | Choices: `1`, `2`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 18 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `interpolation` | `0` | Bits per input sample. |
| `[17:16]` | `order` | `0` | Noise-shaping order. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_pdm.py` (bit-exact/SNR under randomized backpressure).
