# LDPC decoder (z-parallel)

`LiteDSPLDPCDecoderZParallel` — `litedsp.comm.ldpc_parallel` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Foldable lift-parallel normalized min-sum LDPC decoder.

The algorithm and quantization are bit-exact with :class:`LiteDSPLDPCDecoder`; the trade-off
is replicated check-node arithmetic and lane-banked state in exchange for folding the
factor ``z`` by ``parallelism``. With all 27 lanes, an iteration takes
``5*E + 4*m_b = 488`` clocks instead of ``z*(2*E + 2*m_b) = 5400`` clocks in the serial
core. Nine and three lanes take 1,464 and 4,392 clocks/iteration respectively.
Load and output remain bit-serial.

The characterized 27-lane default reaches 108.2/130.2/189.7 MHz on
ECP5/Artix-7/Artix UltraScale+, or 22.1/26.6/38.7 thousand worst-case blocks/s. That is
7.6--9.5x the serial core's family-matched block throughput, at 9--15x its LUT count and
about 18--21x its register count. The 100 MHz engineering target closes on all three
profiles. Its width still makes this a capacity/timing stress configuration rather than a
compact drop-in replacement; ECP5 closure is reviewed across three routes.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `llr_bits` | `4` | int | Signed input LLR width (>= 2; default 4). |
| `max_iters` | `8` | int | Decoding iteration budget per block (1..31; default 8). |
| `parallelism` | `27` | int | Lifted rows processed together: 3, 9, or 27 (default 27). |

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

### `architecture` (read-only, 18 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `parallelism` | `0` | Lifted check rows processed together. |
| `[17:5]` | `cycles_per_iteration` | `0` | Fixed clocks per full layered iteration. |

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
| ecp5 | 10331 | 3553 | 0 | 0 | 92.0 | 100.0 |
| xilinx | 4287 | 3768 | 0 | 0 | 110.7 | 100.0 |
| xilinx_au | 4192 | 3772 | 0 | 0 | 161.3 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
