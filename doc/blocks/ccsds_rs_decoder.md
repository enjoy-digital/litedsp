# CCSDS RS decoder

`LiteDSPCCSDSRSDecoder` — `litedsp.comm.rs` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

CCSDS 131.0-B-5 RS(255,223) decoder with dual-basis stream symbols.

Input/output basis conversion is combinational and cycle-neutral. ``architecture`` selects
the same classic or timing-oriented pipelined schedule as ``LiteDSPRSDecoder``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `architecture` | `"pipelined"` | str | Implementation architecture selector; timing variants publish latency/throughput trade-offs. Choices: `classic`, `pipelined`. |

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

### `status` (read-only, 9 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `corrected` | `0` | Symbols corrected in the last decoded block. |
| `[8]` | `uncorrectable` | `0` | Sticky: a block exceeded the correction capability since clear. |

### `corrected_total` (read-only, 32 bits)

Cumulative corrected symbols since clear.

### `uncorrectable_count` (read-only, 16 bits)

Uncorrectable blocks since clear.

### `clear` (read-write, 1 bit)

Clear the sticky flag and cumulative counters (write to clear).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 3741 | 1482 | 1 | 0 | 102.9 | 100.0 |
| xilinx | 1756 | 1482 | 0 | 0 | 117.9 | 100.0 |
| xilinx_au | 1801 | 1490 | 0 | 0 | 210.3 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_rs.py` (bit-exact/SNR under randomized backpressure).
