# LDPC decoder (802.11n)

`LiteDSPLDPCDecoder` — `litedsp.comm.ldpc` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

802.11n rate-1/2 (648, 324) LDPC decoder: 648 LLRs in, 324 corrected bits out.

Row-layered normalized min-sum (factor 0.75 = x - (x >> 2)), one LLR per beat in
(positive = bit 0 more likely, the :class:`~litedsp.comm.soft_demap.LiteDSPSoftDemapper`
convention), hard-decision message bits out, framed. The 27 check rows of each layer are
processed serially over a single-port APP RAM (n entries) with compressed check messages
(min1/min2/index/signs) per check row; see the module docstring for the schedule, the
internal widths and the measured waterfall. Early termination on an iteration whose
on-the-fly syndrome (parity of the check-node input signs) is clean everywhere;
``iterations``/``parity_ok`` report the last block, ``failures`` counts blocks that
exhausted ``max_iters`` unconverged (sticky count, ``clear`` resets it). Worst-case
``cycles_per_block`` = n + max_iters*z*(2E + 2m_b) + 2k + 4 (~44.5 kcycles at
max_iters = 8; E = 88 edges) plus handshake stalls; early termination shortens it by
~5.4 kcycles per saved iteration. Block boundaries are counted from reset (sink
``first``/``last`` ignored).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `llr_bits` | `4` | int | Signed input LLR width (>= 2; default 4). All internal widths derive from it (APP: llr_bits + 2 bits, check-node |Q| clamp: 2**llr_bits - 1). |
| `max_iters` | `8` | int | Decoding iteration budget per block (1..31; default 8). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | raw |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 28 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[9:0]` | `n` | `0` | Codeword length in bits. |
| `[18:10]` | `k` | `0` | Message length in bits. |
| `[22:19]` | `llr_bits` | `0` | Signed input LLR width. |
| `[27:23]` | `max_iters` | `0` | Iteration budget per block. |

### `status` (read-only, 6 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `iterations` | `0` | Iterations used by the last decoded block. |
| `[5]` | `parity_ok` | `0` | Last block converged to a zero syndrome. |

### `failures` (read-only, 16 bits)

Blocks that exhausted max_iters unconverged since clear.

### `clear` (read-write, 1 bit)

Clear the failure counter (write to clear).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 583 | 147 | 2 | 0 | 81.4 | 100.0 |
| xilinx | 304 | 138 | 1 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_ldpc.py` (bit-exact/SNR under randomized backpressure).
