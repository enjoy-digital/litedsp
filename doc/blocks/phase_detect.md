# Phase detector

`LiteDSPPhaseDetect` — `litedsp.comm.phase_detect` — category `comm`

latency: 18 samples · CSR: no · bypass: no

## Overview

Instantaneous phase ``atan2(Q, I)`` of an I/Q stream (CORDIC vectoring).

Building block for carrier/timing loops. Output is the angle in signed phase units
(full circle = 2**angle_width).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `angle_width` | `16` | int | Output angle resolution in bits (full circle = 2**angle_width); sets the CORDIC stage count, so latency and resources grow with it. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | raw |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_phase_detect.py` (bit-exact/SNR under randomized backpressure).
