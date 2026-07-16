# DUC

`LiteDSPDUC` — `litedsp.mixing.duc` — category `mixing`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Digital up-converter: interpolator + complex mixer (up) + NCO.

Interpolates a baseband I/Q stream up to the high rate and shifts it to the NCO frequency.
Tuning word is the NCO ``phase_inc`` CSR. Canonical TX chain.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `interpolation` | `8` | int | Integer interpolation factor. |
| `method` | `"cic"` | str | Core implementation selector. Choices: `cic`, `fir`. |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `interp_core_config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `rate` | `0` | Interpolation factor R. |
| `[23:16]` | `stages` | `0` | CIC stages N. |

### `nco_phase_inc` (read-write, 32 bits)

Phase increment (sets output frequency).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 705 | 302 | 2 | 7 | 62.3 | — |
| xilinx | 386 | 100 | 1 | 6 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
