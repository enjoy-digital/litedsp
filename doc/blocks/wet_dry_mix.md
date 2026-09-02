# Wet/dry mix

`LiteDSPWetDryMix` — `litedsp.audio.effects` — category `audio`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Two-input gain mix on TDM streams: ``y = dry*sink_dry + wet*sink_wet`` (signed Q1.15 gains).

Both sinks are consumed together (sample-aligned join; put a
:class:`~litedsp.stream.fifo.LiteDSPStreamFIFO` on the dry branch to absorb a wet
branch's pipeline fill). One rounding + saturation, sticky ``sat``, latency 1, two
multipliers.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `2` | int |  |
| `coeff_frac` | `15` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink_dry` | sink | tdm |
| `sink_wet` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `wet` (read-write, 16 bits, reset `0x4000`)

Wet gain (signed Q1.15).

### `dry` (read-write, 16 bits, reset `0x4000`)

Dry gain (signed Q1.15).

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturation` | `0` | Output saturated since the last clear. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 227 | 29 | 0 | 4 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_effects.py` (bit-exact/SNR under randomized backpressure).
