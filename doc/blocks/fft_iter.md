# FFT (iterative)

`LiteDSPFFTIter` — `litedsp.analysis.fft_iter` — category `analysis`

latency: 704 samples · CSR: yes · bypass: no

## Overview

Iterative in-place radix-2 FFT, ``N`` points, natural-order output (BRAM-mapped).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `N` | `64` | int | Transform size (power of two). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `twiddle_width` | `16` | int | Twiddle-factor width in bits (signed Q1.(W-1)); sets the N/2-entry cos/sin ROM width, the butterfly multiplier size, and the coefficient-quantization noise floor. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `latency` (read-only, 32 bits, reset `0x2c0`)

Iterative FFT burst latency (cycles).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 938 | 91 | 2 | 4 | 59.9 |
| xilinx | 236 | 29 | 1 | 5 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_fft_iter.py` (bit-exact/SNR under randomized backpressure).
