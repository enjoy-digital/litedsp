# Allpass

`LiteDSPAllpass` — `litedsp.filter.extra` — category `filter`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

1st-order allpass ``y[n] = -a*x[n] + x[n-1] + a*y[n-1]`` (flat magnitude), per I/Q.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `frac` | `14` | int | Fractional bits of the control fixed-point format. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `a` (read-write, 16 bits, reset `0x2000`)

Allpass coefficient (Q.frac).

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
