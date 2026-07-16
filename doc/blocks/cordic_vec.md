# CORDIC (vector)

`LiteDSPCORDIC` — `litedsp.generation.cordic` — category `generation`

latency: 18 samples · CSR: yes · bypass: no

## Overview

Pipelined CORDIC (one iteration per stage), gain-compensated, full-circle.

``mode="rotation"``: rotate ``(x, y)`` by ``z`` -> ``(x, y)``. With ``y=0`` and ``x`` at
full scale this yields ``(cos z, sin z)``.
``mode="vectoring"``: ``(x, y)`` -> magnitude ``sqrt(x**2 + y**2)`` on ``mag`` and phase
``atan2(y, x)`` on ``angle``.

Quadrant pre-rotation extends convergence to the full circle; the output is multiplied by
1/K so magnitude/rotation are unity-gain. Pure feedforward pipeline (``latency =
stages + 2``), so backpressure simply freezes it.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `angle_width` | — | none | Phase word width in bits; the full circle spans 2**angle_width (pi = 2**(angle_width-1)). Defaults to data_width. |
| `stages` | — | none | Number of pipelined CORDIC iterations; each adds ~1 bit of result precision and one cycle of latency (latency = stages + 2). Defaults to data_width. |
| `mode` | `"vectoring"` | str | "rotation" (rotate (x, y) by z, e.g. sin/cos generation) or "vectoring" (magnitude on ``mag`` and atan2(y, x) on ``angle``). Choices: `rotation`, `vectoring`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | raw |
| `source` | source | raw |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `latency` (read-only, 16 bits, reset `0x12`)

CORDIC pipeline latency (cycles).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 1839 | 849 | 0 | 1 | 169.6 |
| xilinx | 742 | 827 | 0 | 1 | 186.4 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_cordic.py` (bit-exact/SNR under randomized backpressure).
