# Correlator

`LiteDSPCorrelator` — `litedsp.comm.correlator` — category `comm`

latency: 3 samples · CSR: no · bypass: no

## Overview

Sliding correlation of the I/Q stream against a known real ``sequence``.

Implemented as a complex FIR whose taps are the time-reversed reference (matched filter):
the output peaks when the input aligns with the sequence. For a +/-1 PN/Barker code pass
the code as ``sequence`` (taps become +/- full-scale). Follow with ``LiteDSPMagnitude`` + a
threshold for preamble detection.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `sequence` | `[1, 1, 1, -1, -1, 1, -1]` | list | Reference sequence, values in [-1.0, +1.0]; taps are its time-reversal scaled to full-scale Q1.(data_width-1). Length sets the FIR tap count (one MAC pair per tap). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 927 | 710 | 0 | 14 | 110.5 |
| xilinx | 68 | 198 | 0 | 14 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_correlator.py` (bit-exact/SNR under randomized backpressure).
