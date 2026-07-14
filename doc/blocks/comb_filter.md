# Comb filter

`LiteDSPCombFilter` — `litedsp.filter.extra` — category `filter`

latency: 1 sample · CSR: no · bypass: yes

## Overview

Feed-forward comb ``y[n] = x[n] - x[n-D]`` (nulls at multiples of fs/D), per I/Q.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `depth` | `8` | int | Comb delay D in samples; nulls fall at integer multiples of fs/depth. Sets the size of the per-I/Q circular delay-line memory (depth x data_width bits). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
