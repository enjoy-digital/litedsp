# Magnitude (CORDIC)

`LiteDSPMagnitude` — `litedsp.analysis.magnitude` — category `analysis`

latency: 18 samples · CSR: no · bypass: no

## Overview

Complex magnitude ``|I + jQ|``.

``method="approx"`` (default): alpha-max-beta-min,
``|z| ~= max(|I|, |Q|) + (min(|I|, |Q|) >> beta_shift)`` — cheap (no multiplier), error
within about -12%..+3% of true. ``method="cordic"``: exact (CORDIC vectoring). The output
is one bit wider than the input (magnitude can reach ~1.41x full scale).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `beta_shift` | `2` | int | Right shift applied to ``min(|I|, |Q|)`` in the alpha-max-beta-min sum (beta = 2**-beta_shift); 2 gives the ~-12%..+3% error bound. Used by ``method="approx"`` only. |
| `method` | `"cordic"` | str | Core implementation selector. Choices: `approx`, `cordic`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 1618 | 601 | 0 | 1 | 166.8 |
| xilinx | 540 | 580 | 0 | 1 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_magnitude.py` (bit-exact/SNR under randomized backpressure).
