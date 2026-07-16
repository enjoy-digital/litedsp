# Framer

`LiteDSPStreamFramer` — `litedsp.stream.framing` — category `stream`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Pass I/Q through, asserting ``first`` at sample 0 and ``last`` at sample ``length-1``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `length` | `256` | int | Reset value of the runtime frame length, in samples; ``last`` is asserted every ``length`` transfers (maps to AXI-Stream ``tlast`` for fixed-size DMA packets). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `max_length` | `65536` | int | Upper bound of the runtime ``length`` setting (exclusive); sizes the sample counter and the length CSR (ceil(log2(max_length)) bits). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `length` (read-write, 16 bits, reset `0x100`)

Frame length in samples (assert last every N).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 102 | 16 | 0 | 0 | 267.7 | — |
| xilinx | 27 | 16 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
