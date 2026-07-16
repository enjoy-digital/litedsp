# DDC

`LiteDSPDDC` — `litedsp.mixing.ddc` — category `mixing`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Digital down-converter: NCO + complex mixer (down) + decimator.

Tunes a band centered at the NCO frequency down to baseband and decimates. The tuning word
is the NCO ``phase_inc`` CSR (set it to ``-f_tune`` in phase units). Canonical RX front-end.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `decimation` | `8` | int | Integer decimation factor. |
| `method` | `"cic"` | str | Core implementation selector. Choices: `cic`, `fir`. |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `nco_phase_inc` (read-write, 32 bits)

Phase increment (sets output frequency).

### `decim_core_config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `rate` | `0` | Decimation factor R. |
| `[23:16]` | `stages` | `0` | CIC stages N. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 890 | 317 | 2 | 6 | 82.7 |
| xilinx | 480 | 122 | 1 | 6 | 107.4 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).
