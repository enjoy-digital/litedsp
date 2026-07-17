# Puncturer

`LiteDSPPuncturer` — `litedsp.comm.puncture` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

TX puncturer: drops coded bits of the rate-1/n stream per the puncturing matrix.

One n-bit coded symbol in (:class:`~litedsp.comm.coding.LiteDSPConvEncoder` output), the
kept bits out serially (one bit per beat, row 0 first) — pattern column ``t mod period``
applies to input symbol ``t``. Variable rate (``latency = None``): a symbol takes as many
output beats as its column keeps. ``phase_rst`` (CSR pulse) re-zeros the pattern phase for
subsequently accepted symbols (block-boundary alignment).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `pattern` | `[[1, 0, 1], [1, 1, 0]]` | list | Puncturing matrix as ``n`` lists of 0/1 (row ``j`` for coded stream ``polys[j]``, one column per period position; see the module-level DVB-S constants). Every column must keep at least one bit. Default: ``PUNCTURE_1_2`` (no puncturing). |
| `n` | `2` | int | Coded bits per input symbol (the mother code's 1/n rate; sink data width). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `phase_rst` | `0` | Re-zero the puncturing pattern phase (applies to the next accepted symbol). (pulse) |

### `config` (read-only, 16 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `period` | `0` | Puncturing pattern period (columns). |
| `[15:8]` | `n` | `0` | Coded bits per input symbol (mother code 1/n). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 21 | 8 | 0 | 0 | 363.9 | — |
| xilinx | 12 | 8 | 0 | 0 | — | — |
| xilinx_au | 9 | 8 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_puncture.py` (bit-exact/SNR under randomized backpressure).
