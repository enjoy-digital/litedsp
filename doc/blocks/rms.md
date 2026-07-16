# RMS

`LiteDSPRMS` — `litedsp.level.rms` — category `level`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

RMS magnitude over ``2**window_log2`` samples: ``sqrt(mean(I**2 + Q**2))``.

Accumulates instantaneous power over a window, averages (shift), and takes the square root
(:class:`LiteDSPISqrt`). Emits one RMS value per completed window on ``source`` (framed). The
input is always accepted (the source is produced once per window).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `window_log2` | `8` | int | Reset value of the runtime window setting; the RMS is computed over 2**window_log2 samples. Larger = smoother estimate but slower update rate (one output per window). |
| `max_window_log2` | `20` | int | Upper bound of the runtime ``window_log2`` setting. Sizes the power accumulator (2*data_width + max_window_log2 bits) and the sample counter. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `window` (read-write, 5 bits, reset `0x8`)

RMS window as power of two (2**window_log2).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 1293 | 156 | 0 | 2 | 128.8 |
| xilinx | 262 | 155 | 0 | 2 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_rms.py` (bit-exact/SNR under randomized backpressure).
