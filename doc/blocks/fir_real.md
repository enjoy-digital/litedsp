# FIR (real)

`LiteDSPFIRFilter` — `litedsp.filter.fir` — category `filter`

latency: 3 samples · CSR: no · bypass: yes

## Overview

Pipelined single-rate real FIR filter with stream I/O and round+saturate output.

Computes ``y[k] = sum_t coeffs[t] * x[k-t]``. With
``symmetric=True`` the (linear-phase) filter folds tap pairs to halve the multiplier
count; the caller must provide symmetric coefficients.

Backpressure is handled with an elastic pipeline: the sample shift-register advances only
on real input transfers (so bubbles never enter the convolution history), while the
arithmetic stages and the valid pipeline drain on every accepted output beat.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `32` | int | Number of FIR taps. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `symmetric` | `False` | bool | Fold mirrored tap pairs before the multiply, halving the multiplier count (DSP blocks) for linear-phase filters. The provided coefficients must actually be symmetric. |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |
| `architecture` | `"classic"` | str | ``"classic"`` uses a combinational balanced reduction after the product registers and has three clocks of latency. ``"pipelined"`` registers every adder-tree level, retaining one-sample-per-clock throughput while adding ``ceil(log2(n_products))`` clocks. Choices: `classic`, `pipelined`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_fir.py` (bit-exact/SNR under randomized backpressure).
