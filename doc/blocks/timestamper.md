# Timestamper

`LiteDSPTimestamper` — `litedsp.stream.timestamp` — category `stream`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Tag the I/Q stream with its ingress time (``timestamp``/``stream_id`` params, latency 0).

Passthrough on the payload; the source gains the :func:`litedsp.common.time_param_layout`
params. ``time`` is sampled from the parent-connected :class:`LiteDSPTimeCore`: on a framed
stream the tag is latched at each frame ``first`` and held for the whole frame (all samples
of a frame carry the frame's ingress time — recover sample k's time as ``timestamp + k``);
on an unframed stream (no ``first`` seen) every sample carries its own ingress time.
Ingress time is the acceptance cycle (``valid & ready``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `width` | `64` | int | Timestamp width in bits (match the TimeCore). |
| `stream_id` | `0` | int | Reset value of the 8-bit stream identifier tagged onto every sample (CSR-settable). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `stream_id` (read-write, 8 bits)

Stream identifier tagged onto every sample.

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_timestamp.py` (bit-exact/SNR under randomized backpressure).
