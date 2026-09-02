# I2S receiver

`LiteDSPI2SReceiver` — `litedsp.audio.i2s` — category `audio`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Serial audio receiver (I2S, left/right-justified, TDM) to a channel-tagged TDM stream.

Data is sampled on the BCLK rising edge, MSB first, ``sample_width`` bits per
``slot_width`` slot: I2S (MSB one BCLK after the LRCK transition, left = LRCK low),
left-justified (MSB at the transition, left = LRCK high), right-justified (LSB at the slot
end) and TDM (``lrck`` is a one-BCLK frame-sync pulse, ``n_channels`` consecutive slots).
Words are MSB-aligned into ``data_width`` and tagged with their slot; a word completing
while the previous one is still unread is dropped (sticky ``overrun``). ``mode="master"``
drives ``bclk``/``lrck`` at ``sys_clk / bclk_div``; ``mode="slave"`` follows them (``sys``
>= 4 x BCLK). Source-only, ``latency = None``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `sample_width` | `24` | int |  |
| `slot_width` | `32` | int |  |
| `n_channels` | `2` | int |  |
| `fmt` | `"i2s"` | str | Choices: `i2s`, `left_justified`, `right_justified`, `tdm`. |
| `mode` | `"slave"` | str | Choices: `slave`, `master`. |
| `bclk_div` | `8` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 2 bits, reset `0x1`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `enable` | `1` | Capture words. |
| `[1]` | `clear` | `0` | Clear overrun. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `overrun` | `0` | Sticky: a word was dropped. |

### `config` (read-only, 27 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `fmt` | `0` | 0 i2s, 1 left-justified, 2 right-justified, 3 tdm. |
| `[2]` | `master` | `0` | Master (drives bclk/lrck). |
| `[6:3]` | `n_channels` | `0` | Slots per frame. |
| `[12:7]` | `sample_width` | `0` | Bits per sample. |
| `[18:13]` | `slot_width` | `0` | Bits per slot. |
| `[26:19]` | `bclk_div` | `0` | sys_clk / bclk (master). |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_i2s.py` (bit-exact/SNR under randomized backpressure).
