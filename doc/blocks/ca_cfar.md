# CA-CFAR detector

`LiteDSPCACFAR` — `litedsp.radar.cfar` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

One-dimensional cell-averaging CFAR detector on framed cell streams.

A window of ``2*(n_train + n_guard) + 1`` cells slides along each frame (a range profile or a
map row): the cell under test sits in the middle, ``n_guard`` cells on each side are
ignored and the ``n_train`` leading and lagging training cells form the noise estimate.
Runtime ``mode``: 0 cell averaging (``lead + lag``), 1 greatest-of (``2*max``), 2
smallest-of (``2*min``). The threshold is ``alpha * mean`` (``alpha`` unsigned
Q(alpha_width - threshold_frac).threshold_frac, see ``litedsp.radar.design.cfar_alpha``),
computed as ``sum * alpha * round(2**16 / (2*n_train))``, rounded and floored at the runtime
``threshold_min`` (the zero-padded edges see smaller training sums). Frames are
zero-padded: ``first`` clears the window, and after ``last`` the block flushes the trailing
cells with zero neighbours (``n_train + n_guard + 1`` cycles ``sink.ready`` low), so the output has exactly one
beat per input cell with the same framing. Output: the cell, its threshold and the
decision on :func:`~litedsp.common.cell_layout`. ``latency = None`` (the flush); nominal
delay ``n_train + n_guard + 4`` cycles.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_train` | `8` | int |  |
| `n_guard` | `2` | int |  |
| `data_width` | `17` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `alpha_width` | `16` | int |  |
| `threshold_frac` | `8` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | cell |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `alpha` (read-write, 16 bits, reset `0x200`)

Threshold factor on the training mean (unsigned Q.8).

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `mode` | `0` | 0: cell averaging, 1: greatest-of, 2: smallest-of. |

### `config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `n_train` | `0` | Training cells per side. |
| `[15:8]` | `n_guard` | `0` | Guard cells per side. |
| `[23:16]` | `frac` | `0` | Fractional bits of alpha. |

### `threshold_min` (read-write, 17 bits)

Threshold floor (unsigned cell units): guards the zero-padded edges and notches.

### `detections` (read-only, 32 bits)

Detections since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1268 | 625 | 0 | 2 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_cfar.py` (bit-exact/SNR under randomized backpressure).
