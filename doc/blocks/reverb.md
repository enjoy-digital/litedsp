# Reverb

`LiteDSPReverb` — `litedsp.audio.effects` — category `audio`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Schroeder / Freeverb-style reverb: parallel damped feedback combs, series allpasses, mix.

The input fans out to ``len(comb_delays)`` :class:`LiteDSPDelayLine` combs (``feedback =
room_size``, ``damping``, wet ``1/n_combs`` / dry 0), whose outputs are summed and passed
through ``len(allpass_delays)`` series Schroeder allpasses (delay
lines with ``feedback = g``, ``dry = -g``, ``wet = 1``), then mixed with the dry signal by
:class:`LiteDSPWetDryMix` (``wet``/``dry`` controls). Channel ``c`` of the TDM stream adds
``c*stereo_spread`` frames to every delay for a decorrelated stereo tail. All delays are
per channel in one buffer per line. ``room_size``, ``damping``, ``allpass_gain``, ``wet``,
``dry`` are runtime controls; the composite's ``latency`` is the beat-aligned mix latency
(the comb/allpass engines add no sample delay).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `2` | int |  |
| `comb_delays` | `(1116, 1188, 1277, 1356)` | list | Comb delays in frames (Freeverb's first four at 44.1 kHz by default). |
| `allpass_delays` | `(556, 441)` | list | Allpass delays in frames. |
| `stereo_spread` | `23` | int | Extra frames per channel index. |
| `coeff_frac` | `15` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `room_size` (read-write, 16 bits, reset `0x6b84`)

Comb feedback (signed Q1.15): decay time.

### `damping` (read-write, 15 bits, reset `0x1999`)

Comb feedback low-pass (Q0.15): high-frequency decay.

### `allpass_gain` (read-write, 16 bits, reset `0x3fff`)

Allpass diffusion gain (signed Q1.15).

### `wet` (read-write, 16 bits, reset `0x2666`)

Wet gain (signed Q1.15).

### `dry` (read-write, 16 bits, reset `0x5998`)

Dry gain (signed Q1.15).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 33760 | 1439 | 0 | 16 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_effects.py` (bit-exact/SNR under randomized backpressure).
