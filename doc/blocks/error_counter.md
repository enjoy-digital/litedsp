# Error counter

`LiteDSPErrorCounter` — `litedsp.analysis.measure` — category `analysis`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Count mismatches between a reference and a received I/Q stream (synchronous join).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink_ref` | sink | iq |
| `sink_rx` | sink | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `errors` (read-only, 32 bits)

Mismatched samples since clear.

### `total` (read-only, 32 bits)

Compared samples since clear.

### `clear` (read-write, 1 bit)

Reset the counters (write to clear).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 93 | 64 | 0 | 0 | 382.4 | — |
| xilinx | 17 | 64 | 0 | 0 | — | — |
| xilinx_au | 17 | 64 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_measure.py` (bit-exact/SNR under randomized backpressure).
