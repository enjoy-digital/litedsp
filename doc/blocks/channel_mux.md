# Channel mux

`LiteDSPChannelMux` — `litedsp.stream.route` — category `stream`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Route one of ``n`` I/Q sinks to a single source, selected by ``sel`` (runtime).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n` | `2` | int | Number of selectable input channels (sinks). Sizes the ``sel`` signal/CSR; unselected sinks are backpressured (ready held low), not drained. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sinks[0]` | sink | iq |
| `sinks[1]` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `sel` (read-write, 1 bit)

Selected input channel.

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_route.py` (bit-exact/SNR under randomized backpressure).
