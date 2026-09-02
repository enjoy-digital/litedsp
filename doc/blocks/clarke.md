# Clarke (abc -> ab)

`LiteDSPClarke` — `litedsp.motor.transforms` — category `motor`

latency: 1 sample · CSR: no · bypass: no

## Overview

Clarke transform: three-phase a/b/c -> stationary alpha/beta (amplitude-invariant).

``alpha = (2a - b - c)/3`` and ``beta = (b - c)/sqrt(3)``: a balanced set of peak ``A``
maps to a space vector of magnitude ``A``. With ``three_wire=True`` the block assumes
``a + b + c = 0`` (two measured phase currents, the third implied by Kirchhoff): ``alpha =
a`` exactly and ``beta = (a + 2b)/sqrt(3)``, one multiplier fewer. Constants are Q1.15 and
each output is rounded + saturated once. Output on ``iq_layout`` (i = alpha, q = beta),
fixed 1-cycle latency.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `three_wire` | `False` | bool | Use phases a and b only (``c = -a - b`` implied); ``alpha = a`` is then exact. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | abc |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_transforms.py` (bit-exact/SNR under randomized backpressure).
