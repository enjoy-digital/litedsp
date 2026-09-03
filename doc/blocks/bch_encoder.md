# BCH encoder

`LiteDSPBCHEncoder` — `litedsp.comm.bch` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Systematic BCH(n, k) encoder on a bit stream: ``k`` message bits pass through while an
LFSR divides by the generator ``g(x)``, then the ``n - k`` parity bits follow (MSB of the
remainder first). Framed (``first`` / ``last`` per codeword); ``cycles_per_block = n + 1``;
``latency = None``.

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

### `blocks` (read-only, 32 bits)

Codewords sent.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 114 | 61 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_bch.py` (bit-exact/SNR under randomized backpressure).
