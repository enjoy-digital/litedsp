# FM modulator

`LiteDSPFrequencyModulator` — `litedsp.comm.fm_mod` — category `comm`

latency: 2 samples · CSR: yes · bypass: no

## Overview

FM modulator: real samples to a complex exponential whose instantaneous frequency is
``(phase_inc + d / 2**(data_width-1) * deviation) * fs / 2**phase_bits``.

The phase accumulates per accepted sample only (bubbles do not advance it); the cos/sin
come from a quarter-wave ROM (``lut_depth`` entries equivalent). Latency 2. Loops back
through :class:`~litedsp.comm.fm_demod.LiteDSPFMDemod`.

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
| ecp5 | 706 | 91 | 0 | 2 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_fm_mod.py` (bit-exact/SNR under randomized backpressure).
