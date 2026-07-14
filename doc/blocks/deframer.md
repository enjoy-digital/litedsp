# Deframer

`LiteDSPStreamDeframer` — `litedsp.stream.framing` — category `stream`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Pass I/Q through, counting frames (on ``last``) and re-deriving ``first`` after each frame.

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

## Register Map

### `frames` (read-only, 32 bits)

Completed frames since clear.

### `clear` (read-write, 1 bit)

Reset the frame counter (write to clear).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
