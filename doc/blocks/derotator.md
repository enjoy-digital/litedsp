# Derotator (CFO)

`LiteDSPDerotator` — `litedsp.correction.cfo` — category `correction`

latency: 2 samples · CSR: yes · bypass: no

## Overview

Frequency-shift (derotate) an I/Q stream by ``-phase_inc`` (NCO + down-mixer).

Use with a manual ``phase_inc`` (the NCO CSR) to correct a known CFO, or drive
``nco.phase_inc`` from a carrier-recovery loop. ``source = sink * exp(-j*2*pi*f*n)``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
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

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
