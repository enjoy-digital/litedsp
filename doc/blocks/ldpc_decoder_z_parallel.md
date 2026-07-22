# LDPC decoder (z-parallel)

`LiteDSPLDPCDecoderZParallel` — `litedsp.comm.ldpc_parallel` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

27-row-parallel normalized min-sum LDPC decoder.

The algorithm and quantization are bit-exact with :class:`LiteDSPLDPCDecoder`; the trade-off
is replicated check-node arithmetic and lane-banked state in exchange for removing the
factor ``z`` from the per-iteration schedule. With the default code, an iteration takes
``5*E + 4*m_b = 488`` clocks instead of ``z*(2*E + 2*m_b) = 5400`` clocks in the serial core.
Load and output remain bit-serial, so worst-case ``cycles_per_block`` is 4900 clocks at eight
iterations, excluding handshake stalls (versus 44,500 for the serial architecture).

The characterized default reaches 101.3/122.7/190.3 MHz on
ECP5/Artix-7/Artix UltraScale+, or 20.7/25.0/38.8 thousand worst-case blocks/s. That is
7.7--8.9x the serial core's family-matched block throughput, at 9--14x its LUT count and
about 17--20x its register count. The 100 MHz engineering target closes on all three
profiles. Its width still makes this a capacity/timing stress configuration rather than a
compact drop-in replacement; ECP5 closure is reviewed across three routes.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `llr_bits` | `4` | int | Signed input LLR width (>= 2; default 4). |
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

### `architecture` (read-only, 15 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `parallelism` | `0` | Lifted check rows processed together. |
| `[14:5]` | `cycles_per_iteration` | `0` | Fixed clocks per full layered iteration. |

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
| ecp5 | 9948 | 3413 | 0 | 0 | 86.1 | 100.0 |
| xilinx | 4205 | 3629 | 0 | 0 | 104.3 | 100.0 |
| xilinx_au | 4284 | 3632 | 0 | 0 | 161.7 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
