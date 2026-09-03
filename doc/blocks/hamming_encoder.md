# Hamming encoder

`LiteDSPHammingEncoder` — `litedsp.comm.hamming` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Systematic Hamming encoder on a bit stream: ``k`` message bits in, the ``n = 2^m - 1``
codeword bits out (message first, then the ``m`` parity bits; with ``secded`` an overall
parity bit follows, ``n + 1``). Framed (``first`` on the first codeword bit, ``last`` on the
last); ``cycles_per_block = n (+1) + 1``. ``latency = None``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `m` | `3` | int | Choices: `3`, `4`, `5`, `6`. |
| `secded` | `False` | bool | Choices: `False`, `True`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 17 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `n` | `0` | Codeword bits. |
| `[15:8]` | `k` | `0` | Message bits. |
| `[16]` | `secded` | `0` | Overall parity bit present. |

### `blocks` (read-only, 32 bits)

Codewords sent.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 111 | 48 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_hamming.py` (bit-exact/SNR under randomized backpressure).
