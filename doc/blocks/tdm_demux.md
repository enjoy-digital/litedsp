# TDM demux

`LiteDSPTDMDemux` — `litedsp.stream.route` — category `stream`

latency: 0 samples · CSR: no · bypass: no

## Overview

Split a channel-tagged TDM stream into ``n_channels`` mono streams: every beat is routed
to ``sources[channel]`` (combinational, latency 0; a stalled output stalls the stream).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_channels` | `2` | int |  |
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `sources[0]` | source | real |
| `sources[1]` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_route.py` (bit-exact/SNR under randomized backpressure).
