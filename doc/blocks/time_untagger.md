# Time untagger

`LiteDSPTimeUntagger` — `litedsp.stream.timestamp` — category `stream`

latency: 0 samples · CSR: no · bypass: no

## Overview

Strip the ``timestamp``/``stream_id`` params: tagged I/Q -> plain I/Q (latency 0).

The boundary back into time-agnostic DSP blocks (inverse of :class:`LiteDSPTimestamper` on
the layout; the payload and ``first``/``last`` framing pass through untouched).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `width` | `64` | int | Timestamp width in bits of the tagged sink (match the tagging point). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_timestamp.py` (bit-exact/SNR under randomized backpressure).
