# CIC decimator

`LiteDSPCICDecimator` — `litedsp.filter.cic` — category `filter`

latency: 1 sample · CSR: yes · bypass: no

## Overview

CIC decimator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N``, rescaled to width.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `decimation` | `8` | int | Integer decimation factor. |
| `n_stages` | `3` | int | Number of CIC integrator/comb stages (N in the literature). |
| `diff_delay` | `1` | int | CIC comb differential delay (M in the literature). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `rate` | `0` | Decimation factor R. |
| `[23:16]` | `stages` | `0` | CIC stages N. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 566 | 484 | 0 | 0 | 68.0 | — |
| xilinx | 776 | 484 | 0 | 0 | 82.6 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_cic.py` (bit-exact/SNR under randomized backpressure).
