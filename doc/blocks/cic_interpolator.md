# CIC interpolator

`LiteDSPCICInterpolator` — `litedsp.filter.cic` — category `filter`

latency: 1 sample · CSR: yes · bypass: no

## Overview

CIC interpolator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N / R``, rescaled.

``staged=False`` retains the one-cycle compatibility architecture.  ``staged=True`` uses
elastic one-subtractor/adder stages, preserves the numerical output sequence, and increases
no-stall latency to ``2*n_stages`` clocks while retaining one output sample per clock.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `interpolation` | `8` | int | Integer interpolation factor. |
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
| `[15:0]` | `rate` | `0` | Interpolation factor R. |
| `[23:16]` | `stages` | `0` | CIC stages N. |
| `[24]` | `staged` | `0` | One when the registered-stage architecture is selected. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 596 | 615 | 0 | 0 | 207.0 | 100.0 |
| xilinx | 486 | 615 | 0 | 0 | 202.3 | 100.0 |
| xilinx_au | 486 | 615 | 0 | 0 | 457.2 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_cic.py` (bit-exact/SNR under randomized backpressure).
