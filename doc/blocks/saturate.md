# Saturate

`LiteDSPSaturate` — `litedsp.level.saturate` — category `level`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Rescale a complex I/Q stream by a fixed right ``shift`` with round-half-up + saturation.

A thin standalone wrapper around the shared fixed-point helpers, useful as an explicit
level/scaling stage between blocks. ``shift = 0`` makes it a pure saturating passthrough.
``sat`` is a sticky overflow flag (cleared by ``clear_sat``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `in_width` | — | none | Width in bits of each signed input I/Q component (defaults to data_width). Set it wider than data_width to narrow a grown datapath back down with round + saturate. |
| `shift` | `0` | int | Output rescale shift (defaults to data_width - 1). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear_sat` | `0` | Clear saturation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturation` | `0` | Output saturated since last clear. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 67 | 33 | 0 | 0 | 572.0 |
| xilinx | 55 | 33 | 0 | 0 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_saturate.py` (bit-exact/SNR under randomized backpressure).
