# Histogram

`LiteDSPHistogram` — `litedsp.analysis.histogram` — category `analysis`

latency: variable (data-dependent) · CSR: no · bypass: no

## Overview

Sample-distribution histogram (e.g. for ADC characterization).

Bins by the top ``bits`` of ``(x + 2**(data_width-1))`` (offset to unsigned). Accumulates
over ``2**window_log2`` samples into a ``2**bits``-entry RAM, then streams the bin counts
(natural order, framed) while backpressuring the input; each bin is cleared as it is read,
so the next window starts from zero.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `bits` | `8` | int | Bin-address width: samples are binned by their top ``bits`` (offset-binary), giving ``2**bits`` bins and sizing the count RAM depth. |
| `window_log2` | `12` | int | Samples accumulated per window as a power of two (``2**window_log2``); sets the bin count width to window_log2 + 1 bits so a single bin can hold a full window. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 389 | 22 | 0 | 0 | 100.1 | — |
| xilinx | 110 | 22 | 0 | 0 | — | — |
| xilinx_au | 116 | 21 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
