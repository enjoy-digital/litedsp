# Window

`LiteDSPWindow` — `litedsp.analysis.window` — category `analysis`

latency: 2 samples · CSR: no · bypass: no

## Overview

Apply a length-``n`` window to a complex I/Q stream, framed every ``n`` samples.

Each I/Q sample is multiplied by the real window coefficient for its position in the frame
(round + saturate). ``source.first`` / ``source.last`` mark frame boundaries so a
downstream FFT can align frames. The window is fixed at build time (``window``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n` | `64` | int | Window length in samples (frame size); sets the coefficient ROM depth and must match the downstream FFT size. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `window` | `"hann"` | str | Window function (rect/hann/hamming/blackman). Choices: `hann`, `hamming`, `blackman`, `rect`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 391 | 82 | 0 | 2 | 99.9 | — |
| xilinx | 124 | 54 | 0 | 2 | — | — |
| xilinx_au | 119 | 54 | 0 | 2 | 326.7 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_window.py` (bit-exact/SNR under randomized backpressure).
