# Hamming decoder

`LiteDSPHammingDecoder` — `litedsp.comm.hamming` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Hamming decoder: ``n (+1)`` codeword bits in, ``k`` corrected message bits out (framed).

RECEIVE accumulates the syndrome (XOR of the parity columns of the received ones) and the
overall parity; DECIDE flips the bit whose column equals the syndrome (single error) or,
with ``secded``, flags a double error (syndrome non-zero with even overall parity) and passes
the message through uncorrected (``uncorrectable``, counted). Status: ``corrected`` (last
block), ``corrected_total``, ``uncorrectable`` sticky, ``uncorrectable_count``, ``clear``.
``cycles_per_block = n (+1) + 1 + k``; ``latency = None``.

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
| `[16]` | `secded` | `0` | Double-error detection. |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the uncorrectable flag. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `corrected` | `0` | The last block was corrected. |
| `[1]` | `uncorrectable` | `0` | Sticky: a double error was detected. |

### `corrected_total` (read-only, 32 bits)

Blocks corrected since reset.

### `uncorrectable_count` (read-only, 32 bits)

Double errors since reset.

### `blocks` (read-only, 32 bits)

Blocks decoded.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 284 | 141 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_hamming.py` (bit-exact/SNR under randomized backpressure).
