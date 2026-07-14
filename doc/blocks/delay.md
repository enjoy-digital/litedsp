# Delay

`LiteDSPDelay` — `litedsp.stream.delay` — category `stream`

latency: 1 sample · CSR: no · bypass: no

## Overview

Delay an I/Q stream by ``depth`` cycles (data and valid travel together).

A simple pipeline of register stages used to time-align parallel branches by a known
latency. Under backpressure all branches stall identically, so the alignment in samples is
preserved. ``depth = 0`` is a passthrough.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `depth` | `1` | int | Delay in samples (>= 0; 0 = pure passthrough). Costs one I/Q register stage (2*data_width + 1 flip-flops) per unit of delay. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_delay.py` (bit-exact/SNR under randomized backpressure).
