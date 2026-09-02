# SVPWM modulator

`LiteDSPSVPWM` — `litedsp.motor.svpwm` — category `motor`

latency: 3 samples · CSR: yes · bypass: no

## Overview

Space-vector modulator: alpha/beta voltage vector -> three signed phase duties.

Inverse Clarke (kept two bits wider, one rounding) followed by min/max zero-sequence
injection ``v0 = -(max + min)/2``, which is the classic SVPWM waveform: the line-to-line
voltages are unchanged while the linear (unclipped) range extends from a phase peak of
1.0 to ``2/sqrt(3) = 1.1547`` pu of ``V_dc/2``. ``injection`` (runtime, reset from the
constructor) selects it (``"minmax"``) or plain sinusoidal modulation (``"none"``); the
phase duties are saturated to ``+/-1.0`` (over-modulation clamp) and map to 0..100 % in
:class:`~litedsp.motor.pwm.LiteDSPPWM`. Fixed 3-cycle latency, one multiplier.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `injection` | `"minmax"` | str | Zero-sequence injection at reset: ``"minmax"`` (space vector) or ``"none"``. Choices: `minmax`, `none`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | abc |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit, reset `0x1`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `injection` | `1` |  ``0b0``: Sinusoidal modulation (no zero sequence).; ``0b1``: Space-vector (min/max zero-sequence injection). |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_svpwm.py` (bit-exact/SNR under randomized backpressure).
