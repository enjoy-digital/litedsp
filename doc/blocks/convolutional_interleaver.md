# Convolutional interleaver

`LiteDSPConvolutionalInterleaver` — `litedsp.comm.conv_interleaver` — category `comm`

latency: 2 samples · CSR: yes · bypass: yes

## Overview

Forney convolutional interleaver: branch ``j`` delays by ``j * depth`` symbols (DVB:
``branches=12, depth=17`` bytes); all lines share one RAM of ``depth * B (B-1) / 2`` symbols.
Latency 2; ``bypass``; ``phase_rst`` restarts the commutator.

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
| ecp5 | 434 | 158 | 1 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_conv_interleaver.py` (bit-exact/SNR under randomized backpressure).
