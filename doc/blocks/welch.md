# Welch PSD

`LiteDSPWelchPSD` — `litedsp.analysis.welch` — category `analysis`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Windowed, averaged power spectral density: Window -> FFT -> PSD.

Applies a window before the FFT (reducing spectral leakage vs a bare PSD) and averages
``2**avg_log2`` frames. Output is the averaged spectrum in natural bin order. (Segment
*overlap* is not yet implemented — a future refinement.)

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `N` | `64` | int | Transform size (power of two). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `avg_log2` | `2` | int | Windowed FFT frames averaged per emitted spectrum, as a power of two (``2**avg_log2``); more averaging lowers the variance of the estimate but lengthens the update interval. |
| `window` | `"hann"` | str | Window function (rect/hann/hamming/blackman). Choices: `hann`, `hamming`, `blackman`, `rect`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `psd_control` (read-only, 8 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `avg_log2` | `0` | Averaging exponent (frames = 2**avg_log2). |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_welch.py` (bit-exact/SNR under randomized backpressure).
