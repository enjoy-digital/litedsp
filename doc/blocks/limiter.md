# Limiter (lookahead)

`LiteDSPCompressor` — `litedsp.audio.dynamics` — category `audio`

latency: 15 samples · CSR: yes · bypass: yes

## Overview

Dynamics processor (compressor, limiter, expander/gate) with a log-domain gain computer.

Per beat of the TDM stream the sidechain measures the level ``L`` of the channel in the
log2 domain (Q.8: ``L = log2(|x| / FS)``, peak, or half the log of a per-channel
one-pole mean square, ``detector = 1``, through :class:`~litedsp.level.logdb.LiteDSPLog2`
with its LUT mantissa), computes the gain reduction ``gr = slope_above*max(L - threshold,
0) + slope_below*max(threshold - L, 0)`` (hard knee; ``slope_above = 1 - 1/ratio`` for a
compressor, 1.0 for a limiter; ``slope_below = ratio - 1`` for an expander/gate), clamped
to ``gr_max``, smooths it with attack/release one-pole coefficients (Q0.16, state in
Q7.24 so slow releases have no dead band), applies ``makeup`` and converts the log gain
back through :class:`~litedsp.level.logdb.LiteDSPExp2` (Q5.19, up to +24 dB); the gain
multiplies the sample delayed by ``lookahead`` frames (the sidechain sees the undelayed
sample, so a limiter can act before the peak). ``stereo_link`` drives all channels from
the loudest channel of the previous frame with one shared smoother. ``preset`` only sets
the control reset values; every parameter is a runtime control. One shared multiplier;
``cycles_per_sample`` is documented by the ``cycles_per_sample`` attribute (about 16).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `2` | int | Channels in the TDM frame (1 = mono, real layout). |
| `lookahead` | `32` | int | Delay of the gain-applied signal in frames (0 = none). |
| `preset` | `"limiter"` | str | ``"compressor"`` (-20 dB, 4:1, 10/100 ms), ``"limiter"`` (-1 dBFS, instant attack, 50 ms release) or ``"gate"`` (-50 dB, 1:8, 1/100 ms): reset values of the controls. Choices: `compressor`, `limiter`, `gate`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `threshold` (read-write, 16 bits, reset `0xffd5`)

Threshold in log2 units re full scale (signed Q.8: 256 = 6.02 dB).

### `slope_above` (read-write, 20 bits, reset `0x10000`)

Gain-reduction slope above the threshold (Q4.16; 1 - 1/ratio, 1.0 = limiter).

### `slope_below` (read-write, 20 bits)

Gain-reduction slope below the threshold (Q4.16; ratio - 1 for an expander/gate).

### `attack` (read-write, 17 bits, reset `0xffff`)

Attack smoothing coefficient (Q0.16; 65535 = instantaneous).

### `release` (read-write, 17 bits, reset `0x1b`)

Release smoothing coefficient (Q0.16).

### `gr_max` (read-write, 15 bits, reset `0x9f7`)

Maximum gain reduction (Q7.8 log2 units).

### `makeup` (read-write, 16 bits)

Make-up gain (signed Q.8 log2 units).

### `control` (read-write, 11 bits, reset `0x60`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `detector` | `0` | 0: peak, 1: RMS (one-pole mean square). |
| `[7:4]` | `rms_shift` | `6` | RMS averaging shift. |
| `[8]` | `stereo_link` | `0` | Drive all channels from the loudest one. |
| `[9]` | `bypass` | `0` | Pass beats through unchanged. |
| `[10]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 17 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[14:0]` | `gain_reduction` | `0` | Last gain reduction (Q7.8). |
| `[16]` | `saturation` | `0` | Output saturated since the last clear. |

### `config` (read-only, 26 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `n_channels` | `0` | Channels in the TDM frame. |
| `[23:8]` | `lookahead` | `0` | Lookahead in frames. |
| `[25:24]` | `preset` | `0` |  ``0b00``: compressor; ``0b01``: limiter; ``0b10``: gate |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_dynamics.py` (bit-exact/SNR under randomized backpressure).
