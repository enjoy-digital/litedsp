# OFDM CP remove

`LiteDSPCPRemove` — `litedsp.comm.ofdm` — category `comm`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Remove a cyclic prefix: (CP + N)-sample symbols in, framed N-sample symbols out.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `fft_size` | `64` | int | OFDM symbol length N in samples passed through per symbol (framed with ``first``/``last`` for the FFT). |
| `cp_len` | `16` | int | Cyclic-prefix length in samples, dropped from the head of each symbol (0 < cp_len < fft_size). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

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
| `[15:0]` | `fft_size` | `0` | Symbol length N. |
| `[31:16]` | `cp_len` | `0` | Cyclic-prefix length. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_ofdm.py` (bit-exact/SNR under randomized backpressure).
