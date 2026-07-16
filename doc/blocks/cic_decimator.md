# CIC decimator

`LiteDSPCICDecimator` — `litedsp.filter.cic` — category `filter`

latency: 1 sample · CSR: yes · bypass: no

## Overview

CIC decimator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N``, rescaled to width.

``staged=False`` retains the one-cycle compatibility architecture.  ``staged=True`` uses
elastic one-adder/subtractor stages, sustains one input sample per clock, and preserves the
numerical sequence while increasing no-stall latency to ``2*n_stages`` clocks.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `decimation` | `8` | int | Integer decimation factor. |
| `n_stages` | `3` | int | Number of CIC integrator/comb stages (N in the literature). |
| `diff_delay` | `1` | int | CIC comb differential delay (M in the literature). |
| `staged` | `False` | bool | Select the elastic registered-stage CIC architecture (higher latency, one sample per clock). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 25 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `rate` | `0` | Decimation factor R. |
| `[23:16]` | `stages` | `0` | CIC stages N. |
| `[24]` | `staged` | `0` | One when the registered-stage architecture is selected. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 520 | 665 | 0 | 0 | 309.8 | 100.0 |
| xilinx | 508 | 667 | 0 | 0 | 252.7 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_cic.py` (bit-exact/SNR under randomized backpressure).
