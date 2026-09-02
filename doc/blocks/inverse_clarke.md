# Inverse Clarke

`LiteDSPInverseClarke` — `litedsp.motor.transforms` — category `motor`

latency: 1 sample · CSR: no · bypass: no

## Overview

Inverse Clarke transform: stationary alpha/beta -> three-phase a/b/c.

``a = alpha``, ``b = (-alpha + sqrt(3)*beta)/2``, ``c = (-alpha - sqrt(3)*beta)/2`` with
one Q1.15 rounding + saturation per phase. A vector of magnitude above 1.0 pu saturates
(phase voltages reach 1.1547 pu in the space-vector linear range), which is why
:class:`~litedsp.motor.svpwm.LiteDSPSVPWM` keeps its own wider inverse Clarke. Fixed
1-cycle latency.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | abc |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 228 | 51 | 0 | 1 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_transforms.py` (bit-exact/SNR under randomized backpressure).
