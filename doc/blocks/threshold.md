# Threshold (hysteresis)

`LiteDSPThreshold` — `litedsp.image.point` — category `image`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Binary threshold with hysteresis along the scan line (mono).

The output is full scale when the pixel is at or above ``high``, zero when below ``low``, and
keeps the previous decision in between (a Schmitt trigger along the line: the state resets
at ``first`` and at every ``eol``); ``low = high`` gives a plain threshold. ``invert`` swaps
the two levels. Runtime ``high`` / ``low``; ``bypass``. Latency 1.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `8` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `high` | `128` | int |  |
| `low` | — | none |  |
| `invert` | `False` | bool |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | pixel |
| `source` | source | pixel |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `levels` (read-write, 24 bits, reset `0x800080`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `high` | `128` | Set level. |
| `[23:16]` | `low` | `128` | Reset level (<= high). |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `invert` | `0` | Swap the output levels. |

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 85 | 13 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
