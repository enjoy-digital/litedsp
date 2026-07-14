# Split (fan-out)

`LiteDSPSplit` — `litedsp.stream.split` — category `stream`

latency: 0 samples · CSR: no · bypass: no

## Overview

Fan-out one I/Q stream to ``n`` identical sources (all consumed together).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n` | `2` | int | Number of duplicated output streams (>= 1). The fan-out is atomic, so the slowest branch paces the whole stream (every source sees exactly the same transfers). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `sources[0]` | source | iq |
| `sources[1]` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_split.py` (bit-exact/SNR under randomized backpressure).
