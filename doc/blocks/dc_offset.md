# DC offset

`LiteDSPDCOffset` — `litedsp.correction.dc_offset` — category `correction`

latency: 1 sample · CSR: no · bypass: yes

## Overview

Estimate and remove a DC offset per I/Q with a leaky-integrator mean.

``mean += (x - mean) >> mu`` (pole ``1 - 2**-mu``); output ``x - round(mean)``. Larger
``mu`` = slower/finer estimate. The current estimates are exposed (``mean_i``/``mean_q``)
for monitoring; this is the adaptive cousin of the multiplier-free DC blocker.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `mu` | `10` | int | Leaky-integrator pole shift: mean += (x - mean) >> mu (pole 1 - 2**-mu). Larger mu = slower, finer DC estimate; adds mu fractional bits to each mean accumulator. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
