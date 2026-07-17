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
| `fir_architecture` | `"classic"` | str | Choices: `classic`, `pipelined`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `interp_core_config` (read-only, 25 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `rate` | `0` | Interpolation factor R. |
| `[23:16]` | `stages` | `0` | CIC stages N. |
| `[24]` | `staged` | `0` | One when the registered-stage architecture is selected. |

### `nco_phase_inc` (read-write, 32 bits)

Phase increment (sets output frequency).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 763 | 374 | 2 | 6 | 91.0 | 100.0 |
| xilinx | 381 | 142 | 1 | 6 | 102.4 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
