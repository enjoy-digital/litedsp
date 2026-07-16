# RS encoder (255,k)

`LiteDSPRSEncoder` — `litedsp.comm.rs` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Systematic RS(255, k) encoder: k message bytes in, n = 255 codeword bytes out.

The k message bytes pass straight through (highest-degree coefficient first) while a
2t-stage LFSR divides by g(x); the 2t parity bytes then drain highest-degree first.
Message boundaries are counted from reset (sink ``first``/``last`` ignored); the output
codeword is framed with ``first``/``last``. See the module docstring for the field and
generator-polynomial conventions (0x11D, fcr = 0; conventional basis, not CCSDS dual-basis).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n` | `255` | int | Codeword length in symbols (bytes); fixed at 255, the native RS length over GF(2^8). |
| `k` | `223` | int | Message length in symbols; n - k = 2t parity symbols are appended (n - k even, t = (n - k)/2 in 1..16; default RS(255, 223), t = 16). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 22 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[8:0]` | `n` | `0` | Codeword length in symbols. |
| `[16:9]` | `k` | `0` | Message length in symbols. |
| `[21:17]` | `t` | `0` | Correctable symbols per codeword. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 487 | 265 | 0 | 0 | 120.3 |
| xilinx | 300 | 267 | 0 | 0 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_rs.py` (bit-exact/SNR under randomized backpressure).
