# PDM DAC

`LiteDSPSigmaDeltaDAC` — `litedsp.audio.pdm` — category `audio`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

PDM DAC: a TDM (or mono) sink feeding one :class:`LiteDSPSigmaDeltaModulator` per channel,
whose bits are clocked out on ``pdm_out[c]`` at ``sys_clk / clk_div`` (``pdm_clk`` pin, the
bit changes on its falling edge). Once streaming has started, a tick with no bit available
(input starved) repeats the last bit and sets the sticky ``underrun`` flag.
Sink-only (``latency = None``); feed it at
``sys_clk / (clk_div * interpolation)`` frames per second.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `1` | int |  |
| `interpolation` | `64` | int | Integer interpolation factor. |
| `order` | `2` | int |  |
| `clk_div` | `16` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the underrun flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `underrun` | `0` | Sticky: a bit tick found no sample. |

### `config` (read-only, 28 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `n_channels` | `0` | Channels. |
| `[11:4]` | `clk_div` | `0` | sys_clk / pdm_clk. |
| `[27:12]` | `interpolation` | `0` | Bits per sample. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 582 | 176 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_pdm.py` (bit-exact/SNR under randomized backpressure).
