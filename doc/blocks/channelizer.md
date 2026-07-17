# Channelizer

`LiteDSPChannelizer` — `litedsp.mixing.channelizer` — category `mixing`

latency: 34 samples · CSR: no · bypass: no

## Overview

Split a wide band into ``n_channels`` uniformly-spaced sub-channels.

Implemented as a bank of DDCs (one per channel, tuned to ``k/n_channels`` and decimated):
correct, portable, and composed from tested blocks. ``self.sources[k]`` is sub-channel ``k``
(baseband, decimated). Resource-optimal sharing via a polyphase-FIR + FFT structure is a
documented future refinement.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_channels` | `4` | int | Number of uniformly-spaced sub-channels; channel ``k`` is centered at ``k/n_channels`` of the input sample rate. Resources scale linearly (one DDC per channel). |
| `decimation` | `4` | int | Integer decimation factor. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `method` | `"fir"` | str | Core implementation selector. Choices: `cic`, `fir`. |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `sources[0]` | source | iq |
| `sources[1]` | source | iq |
| `sources[2]` | source | iq |
| `sources[3]` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 3044 | 1342 | 6 | 24 | 95.8 | 100.0 |
| xilinx | 1327 | 419 | 2 | 24 | 138.7 | 100.0 |
| xilinx_au | 1297 | 420 | 2 | 24 | 255.1 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_channelizer.py` (bit-exact/SNR under randomized backpressure).
