# BCH decoder

`LiteDSPBCHDecoder` — `litedsp.comm.bch` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Bit-serial BCH(n, k) decoder: ``n`` codeword bits in, ``k`` corrected message bits out.

RECEIVE evaluates the ``2t`` syndromes by Horner's rule (one GF multiply per syndrome per
bit) and stores the codeword; BM runs the binary Berlekamp-Massey algorithm serially
(``2t`` iterations of up to ``t + 1`` steps, one GF multiply / division per step through a
small inverse ROM); CHIEN scans the ``n`` positions and flips the roots; OUT streams the ``k``
corrected message bits. A locator degree above ``t`` or a root count below the degree
flags ``uncorrectable`` (the block passes through uncorrected). Status: ``corrected`` (last
block), ``corrected_total``, ``uncorrectable`` sticky, ``uncorrectable_count``, ``blocks``,
``clear``. ``cycles_per_block = n + 2 + 2t(t+2) + n + k + 2``; ``latency = None``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `m` | `4` | int | Choices: `4`, `5`, `6`, `7`, `8`. |
| `t` | `2` | int | Choices: `1`, `2`, `3`, `4`. |
| `field_poly` | — | none |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 20 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `n` | `0` | Codeword bits. |
| `[15:8]` | `k` | `0` | Message bits. |
| `[19:16]` | `t` | `0` | Correctable errors. |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the uncorrectable flag. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `corrected` | `0` | The last block was corrected. |
| `[1]` | `uncorrectable` | `0` | Sticky: a block could not be corrected. |

### `corrected_total` (read-only, 32 bits)

Blocks corrected.

### `uncorrectable_count` (read-only, 32 bits)

Uncorrectable blocks.

### `blocks` (read-only, 32 bits)

Blocks decoded.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1329 | 379 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_bch.py` (bit-exact/SNR under randomized backpressure).
