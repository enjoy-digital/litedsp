# Sin/Cos (angle)

`LiteDSPSinCos` — `litedsp.motor.transforms` — category `motor`

latency: 1 sample · CSR: no · bypass: no

## Overview

Angle stream -> ``(cos, sin)`` unit vector on ``iq_layout`` (i = cos, q = sin).

``method="rom"``: quarter-wave sine ROM addressed by the top ``log2(lut_depth)`` angle
bits (the NCO's table, bit-identical to the full-period tables), 1-cycle latency, no DSP.
``method="cordic"``: :class:`~litedsp.generation.cordic.LiteDSPCORDIC` rotation of the
full-scale vector by the angle (``stages + 3`` cycles, no ROM, full angle resolution).
Full scale is ``2**(data_width-1) - 1`` (0.99997 pu), as for the NCO.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `angle_width` | `16` | int | Angle word width; the full circle spans ``2**angle_width`` (CORDIC/NCO convention). |
| `lut_depth` | `1024` | int | ROM entries per turn (power of two >= 8, <= 2**angle_width); the angle is truncated to ``log2(lut_depth)`` bits (``method="rom"`` only). |
| `method` | `"rom"` | str | ``"rom"`` (table lookup) or ``"cordic"`` (rotation pipeline). Choices: `rom`, `cordic`. |
| `stages` | — | none | CORDIC iterations (``method="cordic"``; defaults to ``data_width``). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | angle |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 614 | 23 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_transforms.py` (bit-exact/SNR under randomized backpressure).
