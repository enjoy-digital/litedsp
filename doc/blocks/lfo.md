# LFO

`LiteDSPLFO` — `litedsp.audio.effects` — category `audio`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Low-frequency oscillator: sine (quarter-wave ROM), triangle, saw or square, with amplitude.

A ``phase_bits`` accumulator advances by ``phase_inc`` per accepted sample (the NCO's
handshake: backpressure never skips or repeats a sample); the top phase bits select the
shape sample, scaled by the Q1.15 ``amplitude``. Feeds the modulation input of
:class:`LiteDSPDelayLine` (chorus / flanger / vibrato) or any control port. Latency 1.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `phase_bits` | `32` | int | Accumulator width (frequency resolution ``f_s / 2**phase_bits``). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `lut_depth` | `256` | int | Sine ROM entries per period (power of two >= 8). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `phase_inc` (read-write, 32 bits)

Phase increment per sample (frequency = phase_inc * f_s / 2**phase_bits).

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `shape` | `0` |  ``0b00``: Sine.; ``0b01``: Triangle.; ``0b10``: Saw.; ``0b11``: Square. |

### `amplitude` (read-write, 16 bits, reset `0x7fff`)

Output amplitude (signed Q1.15, 1.0 = full scale).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_effects.py` (bit-exact/SNR under randomized backpressure).
