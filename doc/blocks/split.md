# Split (fan-out)

`LiteDSPSplit` — `litedsp.stream.split` — category `stream`

latency: 0 samples · CSR: no · bypass: no

## Overview

Fan-out one stream to ``n`` identical sources (every source sees every sample).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n` | `2` | int | Number of duplicated output streams (>= 1). Each source sees exactly the same transfers, and the sink sample is consumed once every source has taken it, so the slowest branch paces the whole stream. A source's ``valid`` does not depend on any ``ready``: a branch that takes the sample early is masked (``valid`` low) until the other branches have taken it too, so consumers that wait for ``valid`` before raising ``ready`` (AXI-legal) or that join the branches again (e.g. both inputs of :class:`~litedsp.mixing.mixer.LiteDSPMixer`) cannot deadlock. With every source ready the sample passes in the same cycle (no latency, one sample per clock). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `layout` | — | none | Payload layout (default ``iq_layout(data_width)``); any layout works (real, TDM, abc). |

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
