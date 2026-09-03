# OS-CFAR detector

`LiteDSPOSCFAR` — `litedsp.radar.cfar` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

One-dimensional ordered-statistic CFAR detector on framed cell streams.

Same sliding window, zero padding and flush as :class:`LiteDSPCACFAR`, but the noise
estimate is the ``rank``-th smallest (0-based, runtime) of the ``2*n_train`` training cells,
which a single interferer or a neighbouring target cannot capture (a CA mean would). The
rank is found in parallel (``(2T)^2`` comparators, ``n_train <= 8``): each training cell
counts the cells below it (ties broken by position) and the one whose count equals the rank
is selected. ``threshold = rounded(stat * alpha, threshold_frac)`` saturated and floored
at ``threshold_min``; ``rank`` resets to ``round(0.75 * 2T) - 1`` (the usual 3/4 quantile).
Output on :func:`~litedsp.common.cell_layout`; ``latency = None`` (the flush).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_train` | `4` | int |  |
| `n_guard` | `2` | int |  |
| `rank` | — | none |  |
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

### `alpha` (read-write, 16 bits, reset `0x400`)

Threshold factor on the ranked training cell (unsigned Q.8).

### `control` (read-write, 3 bits, reset `0x5`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[2:0]` | `rank` | `5` | 0-based rank of the training cell used as the noise estimate. |

### `config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `n_train` | `0` | Training cells per side. |
| `[15:8]` | `n_guard` | `0` | Guard cells per side. |
| `[23:16]` | `frac` | `0` | Fractional bits of alpha. |

### `threshold_min` (read-write, 17 bits)

Threshold floor (unsigned cell units).

### `detections` (read-only, 32 bits)

Detections since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1744 | 445 | 0 | 1 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_cfar.py` (bit-exact/SNR under randomized backpressure).
