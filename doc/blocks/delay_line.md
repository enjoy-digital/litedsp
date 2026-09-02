# Delay line (echo)

`LiteDSPDelayLine` — `litedsp.audio.effects` — category `audio`

latency: 7 samples · CSR: yes · bypass: yes

## Overview

Feedback delay line with damping, wet/dry mix and optional modulated fractional delay.

Per beat of the TDM stream (per-channel buffer and state): the delayed sample ``d`` is read
``delay`` frames back (with ``modulation=True``: ``delay + mod*mod_depth`` frames, ``mod``
a Q1.15 sample from ``sink_mod`` consumed once per frame, with linear interpolation of the
fractional part -- chorus / flanger / vibrato), low-pass filtered in the feedback path
(``filt += (d - filt)*(1 - damping)``), written back as ``x + feedback*filt`` and mixed:
``y = dry*x + wet*d``. Coefficients are signed Q1.15 (``damping`` Q0.15). The same block
is the reverb's feedback comb (``wet = 1, dry = 0``) and Schroeder allpass (``feedback =
g, wet = 1, dry = -g, damping = 0``). One multiplier, ``cycles_per_sample`` 8 (10 with
modulation), sticky saturation, bypass.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `2` | int | Channels in the TDM frame (1 = mono, real layout). |
| `max_delay` | `4096` | int | Buffer length per channel in frames (power of two allocated). |
| `coeff_frac` | `15` | int | Fractional bits of the coefficients (15: Q1.15). |
| `modulation` | `False` | bool | Add the ``sink_mod`` modulation input and fractional interpolation. |
| `mod_frac` | `8` | int | Fractional delay bits used by the interpolation. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `delay` (read-write, 12 bits, reset `0x800`)

Delay in frames (samples per channel), <= max_delay - 2.

### `feedback` (read-write, 16 bits)

Feedback gain (signed Q1.15).

### `damping` (read-write, 15 bits)

Feedback low-pass (Q0.15, 0 = off).

### `wet` (read-write, 16 bits, reset `0x4000`)

Wet gain (signed Q1.15).

### `dry` (read-write, 16 bits, reset `0x4000`)

Dry gain (signed Q1.15).

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `bypass` | `0` | Pass beats through unchanged. |
| `[1]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturation` | `0` | Output or buffer saturated since the last clear. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 13118 | 236 | 0 | 2 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_effects.py` (bit-exact/SNR under randomized backpressure).
