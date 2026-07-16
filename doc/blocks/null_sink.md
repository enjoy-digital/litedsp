# Null sink

`LiteDSPNullSink` — `litedsp.stream.csr_io` — category `stream`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Always-ready drain that counts consumed samples (CSR-readable). Terminates a branch.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `count` (read-only, 32 bits)

Samples consumed since clear.

### `clear` (read-write, 1 bit)

Clear the counter (write to clear).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 65 | 32 | 0 | 0 | 305.3 |
| xilinx | 2 | 32 | 0 | 0 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).
