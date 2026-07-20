# CCSDS RS encoder

`LiteDSPCCSDSRSEncoder` — `litedsp.comm.rs` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

CCSDS 131.0-B-5 RS(255,223) encoder with dual-basis stream symbols.

The stream-facing linear maps convert incoming dual-basis message symbols to the
conventional-alpha representation used by the generic encoder and convert its systematic
codeword back to dual basis. They add no cycles and preserve framing/backpressure exactly.

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

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 573 | 265 | 0 | 0 | 223.4 | — |
| xilinx | 255 | 267 | 0 | 0 | 222.0 | — |
| xilinx_au | 254 | 267 | 0 | 0 | 527.3 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_rs.py` (bit-exact/SNR under randomized backpressure).
