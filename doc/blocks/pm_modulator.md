# Phase modulator

`LiteDSPPhaseModulator` — `litedsp.comm.fm_mod` — category `comm`

latency: 2 samples · CSR: yes · bypass: no

## Overview

PM modulator: the carrier phase (``phase_inc`` per sample) plus ``d / 2**(data_width-1) *
deviation`` (a phase offset in accumulator units, ``2**phase_bits`` = one turn). Latency 2.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |
| `lut_depth` | `1024` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `phase_inc` (read-write, 32 bits)

Carrier / centre phase increment per sample.

### `deviation` (read-write, 32 bits)

Phase increment (FM) / phase offset (PM) at full-scale input, in phase-accumulator units.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 727 | 91 | 0 | 2 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_fm_mod.py` (bit-exact/SNR under randomized backpressure).
