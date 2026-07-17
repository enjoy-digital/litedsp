# RS decoder (255,k)

`LiteDSPRSDecoder` — `litedsp.comm.rs` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

RS(255, k) decoder: n = 255 codeword bytes in, k corrected message bytes out.

Full hard-decision decode — syndromes, serial Berlekamp-Massey, serial Chien search with
on-the-fly Forney magnitudes — correcting up to t = (n - k)/2 symbol errors per block
(see the module docstring for the architecture and the worst-case ``cycles_per_block``).
A block beyond the correction capability (locator degree > t, or Chien root count not
matching the locator degree) is passed through *uncorrected* and flagged: ``uncorrectable``
(sticky) is set and ``uncorrectable_count`` increments. ``corrected`` reports the symbols
corrected in the last block (message + parity positions), ``corrected_total`` accumulates;
``clear`` resets the sticky flag and the cumulative counters. Block boundaries are counted
from reset (sink ``first``/``last`` ignored); output blocks are framed with ``first``/``last``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n` | `255` | int | Codeword length in symbols (bytes); fixed at 255, the native RS length over GF(2^8). |
| `k` | `223` | int | Message length in symbols; t = (n - k)/2 symbol errors per block are correctable (n - k even, t in 1..16; default RS(255, 223), t = 16). |
| `architecture` | `"classic"` | str | ``"classic"`` evaluates and advances one Chien position per clock. ``"pipelined"`` registers operands for the Berlekamp-Massey discrepancy and update multipliers before their recurrences, and Lambda's odd/even evaluation plus Omega before the inverse/Forney product. It adds discrepancy/update/inversion and Omega drain clocks plus three clocks per Chien position, while preserving the correction algorithm and all output/status behavior. Choices: `classic`, `pipelined`. |

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

Clear the sticky flag and the cumulative counters (write to clear).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 3780 | 1466 | 1 | 0 | 105.7 | 100.0 |
| xilinx | 1632 | 1466 | 0 | 0 | 121.9 | 100.0 |
| xilinx_au | 1650 | 1474 | 0 | 0 | 229.5 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_rs.py` (bit-exact/SNR under randomized backpressure).
