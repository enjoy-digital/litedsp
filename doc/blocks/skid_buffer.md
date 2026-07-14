# Skid buffer

`LiteDSPSkidBuffer` — `litedsp.stream.buffer` — category `stream`

latency: 0 samples · CSR: no · bypass: no

## Overview

Elastic timing-slack buffer for an I/Q stream (registers both valid and ready paths).

Inserts a pipeline stage on both the valid/payload and ready paths so a long combinational
path can be cut without losing throughput. Thin wrapper over ``stream.Buffer``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
