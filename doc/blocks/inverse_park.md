# Inverse Park

`LiteDSPInversePark` — `litedsp.motor.transforms` — category `motor`

latency: 2 samples · CSR: no · bypass: no

## Overview

Inverse Park transform: rotating d/q + rotor angle -> stationary alpha/beta.

``alpha + j*beta = (d + jq) * exp(+j*theta)``: the complex mixer in up-mode (``a * b``)
with ``b = (cos theta, sin theta)``. Same interface, join and latency as
:class:`LiteDSPPark`.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `angle_width` | `16` | int | Angle word width; the full circle spans ``2**angle_width``. |
| `lut_depth` | `1024` | int | Sin/cos ROM entries per turn (``method="rom"``). |
| `method` | `"rom"` | str | Sin/cos generation: ``"rom"`` (table) or ``"cordic"``. Choices: `rom`, `cordic`. |
| `stages` | — | none | CORDIC iterations (``method="cordic"``; defaults to ``data_width``). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `sink_angle` | sink | angle |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 820 | 189 | 0 | 4 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_transforms.py` (bit-exact/SNR under randomized backpressure).
