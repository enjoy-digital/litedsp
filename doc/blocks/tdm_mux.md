# TDM mux (interleave)

`LiteDSPTDMMux` — `litedsp.stream.route` — category `stream`

latency: 0 samples · CSR: no · bypass: no

## Overview

Interleave ``n_channels`` mono streams into one channel-tagged TDM stream (strict
round-robin: beat ``k`` of the frame is taken from ``sinks[k]``, tagged ``channel = k``).
Combinational (latency 0): a frame advances one beat per accepted transfer, so a slow input
stalls the frame (the outputs of a multi-channel front-end stay time-aligned).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_channels` | `2` | int |  |
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sinks[0]` | sink | real |
| `sinks[1]` | sink | real |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_route.py` (bit-exact/SNR under randomized backpressure).
