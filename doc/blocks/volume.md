# Volume (ramped)

`LiteDSPVolume` — `litedsp.audio.level` — category `audio`

latency: 2 samples · CSR: yes · bypass: yes

## Overview

Per-channel volume with zipper-free gain ramping and mute on a TDM audio stream.

Each channel has an unsigned Q5.``gain_frac`` gain (1.0 = ``2**gain_frac``, up to +30 dB)
and a mute bit; the applied gain slews toward its target by ``delta >> ramp_shift`` per
sample of that channel (at least one LSB, so it converges exactly): a step of ``D`` in
the target is reached in ``~ramp_shift*ln(2)*log2(D)`` samples without zipper noise, a
mute fades to exact zero. ``ramp_enable=0`` applies targets immediately. The product is
rounded once and saturated (sticky ``sat``). ``n_channels=1`` is a mono block on
``real_layout``. Latency 2, one multiplier.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `2` | int | Channels in the TDM frame (1 = mono, real layout). |
| `gain_frac` | — | none | Fractional bits of the gains (default ``data_width - 5``). |
| `ramp_shift` | `8` | int | Ramp speed: the gain moves by (target - gain) >> ramp_shift per sample. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `gain0` (read-write, 24 bits, reset `0x80000`)

Channel 0 gain (unsigned Q5.19, 1.0 = 2**19).

### `gain1` (read-write, 24 bits, reset `0x80000`)

Channel 1 gain (unsigned Q5.19, 1.0 = 2**19).

### `control` (read-write, 10 bits, reset `0x100`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `mute` | `0` | Per-channel mute (faded). |
| `[8]` | `ramp_enable` | `1` | Ramp gain changes. |
| `[9]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturation` | `0` | Output saturated since the last clear. |

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
