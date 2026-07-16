# FIR decimator

`LiteDSPFIRDecimator` — `litedsp.filter.fir_poly` — category `filter`

latency: 33 samples · CSR: yes · bypass: no

## Overview

Decimate-by-R complex FIR with a single time-shared MAC per I/Q.

Collects R input samples then MACs the N taps over the sample window to produce one output
(``y[m] = sum_t c[t]·x[mR-t]``), round + saturate. Coefficients are signed Q1.(W-1).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `32` | int | Number of FIR taps. |
| `decimation` | `8` | int | Integer decimation factor. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coefficients` | — | none | Coefficient list (signed integers, quantized via litedsp.filter.design). |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `taps` | `0` | FIR taps N. |
| `[31:16]` | `rate` | `0` | Decimation factor R. |

### `coeff_reset` (read-write, 1 bit)

Reset the coefficient write pointer to tap 0 (write to strobe).

### `coeff` (read-write, 16 bits)

Write the next FIR coefficient (auto-incrementing tap index).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 503 | 104 | 0 | 2 | 90.3 | — |
| xilinx | 239 | 78 | 0 | 2 | 121.8 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_fir_poly.py` (bit-exact/SNR under randomized backpressure).
