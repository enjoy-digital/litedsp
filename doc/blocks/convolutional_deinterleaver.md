# Convolutional deinterleaver

`LiteDSPConvolutionalDeinterleaver` — `litedsp.comm.conv_interleaver` — category `comm`

latency: 2 samples · CSR: yes · bypass: yes

## Overview

The matching deinterleaver: branch ``j`` delays by ``(B - 1 - j) * depth``; the pair
delays the stream by ``(B - 1) * depth * B`` symbols and spreads a channel burst of ``B``
symbols to errors ``depth * B - 1`` apart.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `branches` | `12` | int |  |
| `depth` | `17` | int |  |
| `width` | `8` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `phase_rst` | `0` | Restart the commutator at branch 0. (pulse) |

### `config` (read-only, 16 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `branches` | `0` | Branches. |
| `[15:8]` | `width` | `0` | Symbol width. |

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 468 | 158 | 1 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_conv_interleaver.py` (bit-exact/SNR under randomized backpressure).
