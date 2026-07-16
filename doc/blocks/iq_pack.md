# I/Q pack

`LiteDSPIQPack` — `litedsp.stream.adapt` — category `stream`

latency: 0 samples · CSR: no · bypass: no

## Overview

Pack ``ratio`` consecutive I/Q samples into one wide ``data`` word (LSB = first sample).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `ratio` | `4` | int | Number of consecutive I/Q samples packed per output word (>= 1); the output ``data`` width is 2*data_width*ratio bits, first sample in the LSBs. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 21 | 133 | 0 | 0 | 122.7 | — |
| xilinx | 10 | 133 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_adapt.py` (bit-exact/SNR under randomized backpressure).
