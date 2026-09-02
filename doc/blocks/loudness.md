# Loudness (BS.1770)

`LiteDSPLoudness` — `litedsp.audio.meter` — category `audio`

latency: 0 samples · CSR: yes · bypass: no

## Overview

ITU-R BS.1770 loudness front-end: K-weighting + per-hop weighted sum of squares (zero-latency
passthrough tap).

The stream is tapped into a side :class:`LiteDSPAudioEQ` (2 bands: the BS.1770 high shelf and
RLB high-pass designed for ``sample_rate``); every K-weighted beat is squared, weighted by its
channel's ``channel_weights`` entry (Q2.14; BS.1770 uses 1.0 for L/R/C and 1.41 for the
surrounds, 0 for the LFE) and accumulated. After ``hop_samples`` frames the accumulator is
latched into ``sum_sq`` (``hop_count`` increments, ``update`` strobes, IRQ ``ev.update``) and
restarted; the host builds the 400 ms momentary / 3 s short-term / gated integrated
loudness from the hop sums (:class:`litedsp.software.drivers.LoudnessDriver`):
``LKFS = -0.691 + 10*log10(sum_sq / (hop_samples * 2**(2*(data_width - 1))))``.

The side engine needs ``cycles_per_sample`` (18) clock cycles per beat; a beat arriving
while it is busy is dropped and sets the sticky ``overrun`` flag.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `2` | int |  |
| `sample_rate` | `48000` | int |  |
| `hop_samples` | `4800` | int |  |
| `channel_weights` | — | none |  |
| `coeff_width` | `32` | int |  |
| `frac_bits` | `28` | int | Fractional bits of the coefficient/control fixed-point format. |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Restart the hop, clear hop_count and overrun. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `overrun` | `0` | Sticky: a beat was dropped by the busy K-weighting engine. |

### `sum_sq` (read-only, 63 bits)

Weighted K-weighted sum of squares of the last hop.

### `hop_count` (read-only, 32 bits)

Hops latched since clear.

### `config` (read-only, 31 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `n_channels` | `0` | Channels. |
| `[9:4]` | `data_width` | `0` | Sample width. |
| `[30:10]` | `hop_samples` | `0` | Frames per hop. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_meter.py` (bit-exact/SNR under randomized backpressure).
