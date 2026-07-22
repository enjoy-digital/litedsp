# Goertzel

`LiteDSPGoertzel` — `litedsp.analysis.goertzel` — category `analysis`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Single-bin DFT (tone detector) via a 2nd-order resonator — one multiplier.

For bin ``k`` of an ``N``-point window, runs ``s = x + (coeff*s1 - s2)`` with
``coeff = 2*cos(2*pi*k/N)``; after ``N`` samples emits the bin power
``s1**2 + s2**2 - coeff*s1*s2`` on ``source`` and restarts. Cheap DTMF / pilot detection.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `N` | `64` | int | Transform size (power of two). |
| `k` | `8` | int | Target DFT bin index (0..N-1); the detected tone frequency is ``k*f_sample/N``. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coeff_frac` | `14` | int | Fractional bits of the fixed-point resonator coefficient ``2*cos(2*pi*k/N)``; more bits sharpen the bin frequency but widen the state registers (data_width + coeff_frac + 4). |
| `architecture` | `"classic"` | str | Implementation architecture selector; timing variants publish latency/throughput trade-offs. Choices: `classic`, `folded`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 16 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `bin` | `0` | Goertzel bin k. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1375 | 336 | 0 | 17 | 50.6 | — |
| xilinx | 764 | 302 | 0 | 12 | — | — |
| xilinx_au | 761 | 323 | 0 | 12 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_goertzel.py` (bit-exact/SNR under randomized backpressure).
