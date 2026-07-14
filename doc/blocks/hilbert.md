# Hilbert

`LiteDSPHilbert` — `litedsp.filter.hilbert` — category `filter`

latency: 3 samples · CSR: no · bypass: no

## Overview

Real -> analytic (complex) signal via a Hilbert FIR.

Two equal-length FIRs run on the real input: the I path is a pure delay (group delay
``(n_taps-1)/2``) and the Q path is a Type-III Hilbert filter (90 deg phase shift). The
matched structure keeps I and Q aligned. Output is the analytic signal (negative-frequency
image suppressed). ``n_taps`` must be odd.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `23` | int | Number of FIR taps. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_hilbert.py` (bit-exact/SNR under randomized backpressure).
