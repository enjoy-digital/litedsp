# CSR source

`LiteDSPCSRSource` — `litedsp.stream.csr_io` — category `stream`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Emit one I/Q sample per ``push`` strobe, with the payload set from CSR registers.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `sample` (read-write, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `i` | `0` | Sample I (signed). |
| `[31:16]` | `q` | `0` | Sample Q (signed). |

### `push` (read-write, 1 bit)

Strobe: emit the sample (write to push).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1 | 33 | 0 | 0 | — | — |
| xilinx | 1 | 33 | 0 | 0 | — | — |
| xilinx_au | 1 | 33 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
