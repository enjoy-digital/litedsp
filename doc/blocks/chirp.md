# Chirp (LFM)

`LiteDSPChirp` — `litedsp.generation.source` — category `generation`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Linear-FM (chirp) I/Q generator: the instantaneous frequency ramps by ``rate`` per sample.

A phase accumulator driven by a frequency accumulator (``freq += rate``; ``phase += freq``)
feeding cos/sin ROMs. Useful for radar and calibration sweeps.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `phase_bits` | `32` | int | Phase accumulator width in bits. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `lut_depth` | `1024` | int | Cos/sin lookup ROM depth (power of two); sets the phase-quantization spur floor. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `start` (read-write, 32 bits)

Chirp start frequency word.

### `rate` (read-write, 32 bits)

Chirp frequency rate per sample.

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_source.py` (bit-exact/SNR under randomized backpressure).
