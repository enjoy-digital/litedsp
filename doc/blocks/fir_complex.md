# FIR (complex)

`LiteDSPFIRFilterComplex` — `litedsp.filter.fir` — category `filter`

latency: 3 samples · CSR: yes · bypass: yes

## Overview

Complex FIR: identical real FIRs on I and Q, shared coefficients, with bypass + CSR.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `32` | int | Number of FIR taps. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `symmetric` | `False` | bool | Fold mirrored tap pairs in both the I and Q FIRs, halving the multiplier count (DSP blocks) for linear-phase filters; the coefficients must actually be symmetric. |
| `coefficients` | — | none | Coefficient list (signed integers, quantized via litedsp.filter.design). |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |
| `architecture` | `"classic"` | str | ``"classic"`` uses the three-clock combinational-reduction filters. ``"pipelined"`` registers every adder-tree level while retaining one complex sample per clock. Choices: `classic`, `pipelined`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `coeffs_coeff_0` (read-write, 16 bits, reset `0x7fff`)

FIR coefficient 0 (signed Qm.n).

### `coeffs_coeff_1` (read-write, 16 bits)

FIR coefficient 1 (signed Qm.n).

### `coeffs_coeff_2` (read-write, 16 bits)

FIR coefficient 2 (signed Qm.n).

### `coeffs_coeff_3` (read-write, 16 bits)

FIR coefficient 3 (signed Qm.n).

### `coeffs_coeff_4` (read-write, 16 bits)

FIR coefficient 4 (signed Qm.n).

### `coeffs_coeff_5` (read-write, 16 bits)

FIR coefficient 5 (signed Qm.n).

### `coeffs_coeff_6` (read-write, 16 bits)

FIR coefficient 6 (signed Qm.n).

### `coeffs_coeff_7` (read-write, 16 bits)

FIR coefficient 7 (signed Qm.n).

### `coeffs_coeff_8` (read-write, 16 bits)

FIR coefficient 8 (signed Qm.n).

### `coeffs_coeff_9` (read-write, 16 bits)

FIR coefficient 9 (signed Qm.n).

### `coeffs_coeff_10` (read-write, 16 bits)

FIR coefficient 10 (signed Qm.n).

### `coeffs_coeff_11` (read-write, 16 bits)

FIR coefficient 11 (signed Qm.n).

### `coeffs_coeff_12` (read-write, 16 bits)

FIR coefficient 12 (signed Qm.n).

### `coeffs_coeff_13` (read-write, 16 bits)

FIR coefficient 13 (signed Qm.n).

### `coeffs_coeff_14` (read-write, 16 bits)

FIR coefficient 14 (signed Qm.n).

### `coeffs_coeff_15` (read-write, 16 bits)

FIR coefficient 15 (signed Qm.n).

### `coeffs_coeff_16` (read-write, 16 bits)

FIR coefficient 16 (signed Qm.n).

### `coeffs_coeff_17` (read-write, 16 bits)

FIR coefficient 17 (signed Qm.n).

### `coeffs_coeff_18` (read-write, 16 bits)

FIR coefficient 18 (signed Qm.n).

### `coeffs_coeff_19` (read-write, 16 bits)

FIR coefficient 19 (signed Qm.n).

### `coeffs_coeff_20` (read-write, 16 bits)

FIR coefficient 20 (signed Qm.n).

### `coeffs_coeff_21` (read-write, 16 bits)

FIR coefficient 21 (signed Qm.n).

### `coeffs_coeff_22` (read-write, 16 bits)

FIR coefficient 22 (signed Qm.n).

### `coeffs_coeff_23` (read-write, 16 bits)

FIR coefficient 23 (signed Qm.n).

### `coeffs_coeff_24` (read-write, 16 bits)

FIR coefficient 24 (signed Qm.n).

### `coeffs_coeff_25` (read-write, 16 bits)

FIR coefficient 25 (signed Qm.n).

### `coeffs_coeff_26` (read-write, 16 bits)

FIR coefficient 26 (signed Qm.n).

### `coeffs_coeff_27` (read-write, 16 bits)

FIR coefficient 27 (signed Qm.n).

### `coeffs_coeff_28` (read-write, 16 bits)

FIR coefficient 28 (signed Qm.n).

### `coeffs_coeff_29` (read-write, 16 bits)

FIR coefficient 29 (signed Qm.n).

### `coeffs_coeff_30` (read-write, 16 bits)

FIR coefficient 30 (signed Qm.n).

### `coeffs_coeff_31` (read-write, 16 bits)

FIR coefficient 31 (signed Qm.n).

### `bypass` (read-write, 1 bit)

Bypass filter (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 209 | 106 | 0 | 2 | 180.0 | — |
| xilinx | 105 | 38 | 0 | 8 | 117.7 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_fir.py` (bit-exact/SNR under randomized backpressure).
