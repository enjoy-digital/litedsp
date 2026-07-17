# Block deinterleaver

`LiteDSPBlockDeinterleaver` — `litedsp.comm.interleaver` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

RX block deinterleaver: the exact inverse of :class:`LiteDSPBlockInterleaver`.

One rows*cols-symbol block is written in arrival (channel) order — column-wise in matrix
terms — and read out row-wise, restoring the original order (for CCSDS: ``rows`` = I
consecutive RS codewords, ready for a time-shared RS decoder; see the module docstring for
the Viterbi -> deinterleaver -> RS-decoder placement). Ping-pong buffered: back-to-back
blocks stream at 1 symbol/cycle. Block boundaries are counted from reset (sink
``first``/``last`` ignored); output blocks are framed with ``first``/``last``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `rows` | `5` | int | Matrix rows = interleaving depth I, matching the transmitter's (default 5). |
| `cols` | `255` | int | Matrix columns = symbols per row (default 255, the RS(255, k) codeword length). |
| `width` | `8` | int | Symbol width in bits (default 8: byte interleaving over RS symbols). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `rows` | `0` | Matrix rows (CCSDS interleaving depth I). |
| `[23:8]` | `cols` | `0` | Matrix columns (RS codeword length for CCSDS). |
| `[31:24]` | `width` | `0` | Symbol width in bits. |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `filled` | `0` | Ping-pong banks holding a complete undrained block (0-2). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 164 | 85 | 2 | 0 | 198.1 | — |
| xilinx | 85 | 55 | 1 | 0 | — | — |
| xilinx_au | 85 | 55 | 1 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_interleaver.py` (bit-exact/SNR under randomized backpressure).
