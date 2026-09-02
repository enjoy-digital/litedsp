# I2S transmitter

`LiteDSPI2STransmitter` — `litedsp.audio.i2s` — category `audio`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Channel-tagged TDM stream to serial audio (I2S, left/right-justified, TDM); the mirror of
:class:`LiteDSPI2SReceiver`.

Beats fill a frame buffer by tag (``sink.ready`` drops once every channel of the next frame
is loaded); the buffer is committed at each frame start and shifted out MSB first, the data
changing on the BCLK falling edge (a slave transmitter needs ``sys`` >= 8 x BCLK for its
output to settle before the master's rising edge). Samples are rounded/saturated from
``data_width`` to ``sample_width``. A frame start without a complete buffer repeats the
previous frame and sets the sticky ``underrun`` flag (once streaming has started).
Sink-only, ``latency = None``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `sample_width` | `24` | int |  |
| `slot_width` | `32` | int |  |
| `n_channels` | `2` | int |  |
| `fmt` | `"i2s"` | str | Choices: `i2s`, `left_justified`, `right_justified`, `tdm`. |
| `mode` | `"master"` | str | Choices: `master`, `slave`. |
| `bclk_div` | `8` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 2 bits, reset `0x1`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `enable` | `1` | Drive sdata (0: silence). |
| `[1]` | `clear` | `0` | Clear underrun. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `underrun` | `0` | Sticky: a frame started without a full buffer. |

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

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 109 | 111 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_i2s.py` (bit-exact/SNR under randomized backpressure).
