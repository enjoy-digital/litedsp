# Bit-reverse reorder

`LiteDSPBitReverse` — `litedsp.analysis.reorder` — category `analysis`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Reorder ``N``-beat frames from bit-reversed to natural order (the FFT's output order).

Frames are written into a ``2 x N`` ping-pong RAM at the bit-reversed address of their
position and read back sequentially, framed with ``first``/``last``; while one bank drains
the other fills, so a continuous stream flows at one beat per cycle after the first frame.
Frame boundaries are counted from reset (the FFT does not carry them through its pipeline):
``fft_latency`` initial fill beats are discarded first, exactly as :class:`LiteDSPPSD` does.
Any payload ``layout`` (default ``iq_layout(data_width)``) is carried as raw bits.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `N` | `64` | int | Frame length (power of two >= 2), the upstream FFT size. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `layout` | — | none |  |
| `fft_latency` | `0` | int | Upstream pipeline fill beats to skip after reset (``LiteDSPFFT.latency``; 0 when the stream is already frame-aligned). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `n` | `0` | Frame length. |
| `[31:16]` | `fft_latency` | `0` | Fill beats skipped after reset. |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `filled` | `0` | Frames buffered (0..2). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 141 | 74 | 1 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_reorder.py` (bit-exact/SNR under randomized backpressure).
