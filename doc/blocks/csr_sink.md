# CSR sink

`LiteDSPCSRSink` — `litedsp.stream.csr_io` — category `stream`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Always-ready sink that latches the last I/Q sample and counts transfers (CSR-readable).

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

### `last` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `i` | `0` | Last sample I. |
| `[31:16]` | `q` | `0` | Last sample Q. |

### `count` (read-only, 32 bits)

Transfers since clear.

### `clear` (read-write, 1 bit)

Clear the transfer counter (write to clear).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 64 | 64 | 0 | 0 | 288.1 | — |
| xilinx | 17 | 64 | 0 | 0 | — | — |
| xilinx_au | 17 | 64 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
