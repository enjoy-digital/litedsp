# FIR decimator

`LiteDSPFIRDecimator` — `litedsp.filter.fir_poly` — category `filter`

latency: 33 samples · CSR: yes · bypass: no

## Overview

Decimate-by-R complex FIR with a single time-shared MAC per I/Q.

Collects R input samples then MACs the N taps over the sample window to produce one output
(``y[m] = sum_t c[t]·x[mR-t]``), round + saturate. Coefficients are signed Q1.(W-1).

``prune_zeros=True`` builds the MAC schedule and coefficient memory from only the non-zero
build-time taps. The omitted positions remain structural zeros and cannot be changed by
runtime coefficient reload; use the default rectangular schedule when every position must
remain writable.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `32` | int | Number of FIR taps. |
| `decimation` | `8` | int | Integer decimation factor. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coefficients` | — | none | Coefficient list (signed integers, quantized via litedsp.filter.design). |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |
| `prune_zeros` | `False` | bool |  |

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

Write the next scheduled FIR coefficient (auto-incrementing MAC slot; structurally pruned zero positions are not writable).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 541 | 168 | 0 | 2 | 108.7 | — |
| xilinx | 283 | 105 | 0 | 2 | 121.8 | — |
| xilinx_au | 257 | 105 | 0 | 2 | 305.1 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_fir_poly.py` (bit-exact/SNR under randomized backpressure).
