# Pattern source

`LiteDSPPatternSource` — `litedsp.generation.pattern` — category `generation`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

I/Q test-pattern generator (constant / counter ramp / PRBS / impulse).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `seed` | `1` | int | Initial LFSR state for the PRBS pattern (truncated to data_width, forced non-zero — the all-zero state locks the LFSR); makes the sequence reproducible for BER tests. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 2 bits, reset `0x1`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `mode` | `1` | Pattern select. 0: const; 1: counter; 2: prbs; 3: impulse |

### `const` (read-write, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `i` | `0` | Constant I. |
| `[31:16]` | `q` | `0` | Constant Q. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 114 | 65 | 0 | 0 | 463.2 | — |
| xilinx | 36 | 65 | 0 | 0 | — | — |
| xilinx_au | 36 | 65 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
