# Timing recovery (M&M)

`LiteDSPTimingRecovery` — `litedsp.comm.timing_recovery` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Symbol timing recovery with an interpolation controller (M&M or Gardner detector).

Maintains a samples-per-symbol estimate ``omega`` and a fractional interpolation phase
``mu``. Each symbol: interpolate (cubic Farrow) at ``mu``, form the timing error, update
``omega += g_omega·e`` (clamped) and ``mu += omega + g_mu·e``, then advance the input by
``floor(mu)`` samples (the integer sample-slip) keeping the fractional part. Input is
nominally ``sps`` samples/symbol; output is one (timing-aligned) sample per symbol.

Detectors (``ted``): ``"mm"`` — Mueller & Muller, decision-directed
(``e = Re{slice(prev)·conj(y) − slice(y)·conj(prev)}``, multiplier-free); ``"gardner"`` —
non-decision-aided (``e = Re{(y − y_prev)·conj(y_mid)}`` with a second interpolation at
the symbol midpoint; modulation-agnostic, locks without carrier lock, for ``sps=2``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `sps` | `2` | int | Nominal input samples per symbol; ``omega`` starts here and is clamped to sps +/- 5%. The Gardner detector assumes sps = 2. |
| `frac` | `16` | int | Fractional bits of the control fixed-point format. |
| `gain_mu` | `0.1` | float | Proportional gain on the fractional interpolation phase ``mu`` (quantized to Q.frac). Larger = faster timing acquisition, more jitter. |
| `gain_omega` | — | none | Integral gain on the samples/symbol estimate ``omega`` (quantized to Q.frac; default gain_mu**2/4, the critically-damped choice). |
| `ted` | `"mm"` | str | Timing error detector: "mm" (Mueller & Muller, decision-directed, multiplier-free) or "gardner" (non-decision-aided, extra midpoint interpolation, needs sps = 2). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `omega` (read-only, 20 bits)

Samples/symbol estimate (Q.frac).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 1030 | 292 | 0 | 16 | 61.3 |
| xilinx | 629 | 244 | 0 | 8 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).
