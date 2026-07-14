# Channel demux

`LiteDSPChannelDemux` — `litedsp.stream.route` — category `stream`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Route a single I/Q sink to one of ``n`` sources, selected by ``sel`` (runtime).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n` | `2` | int | Number of selectable output channels (sources). Sizes the ``sel`` signal/CSR; unselected sources see valid held low (no data is duplicated to them). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `sources[0]` | source | iq |
| `sources[1]` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `sel` (read-write, 1 bit)

Selected output channel.

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_route.py` (bit-exact/SNR under randomized backpressure).
