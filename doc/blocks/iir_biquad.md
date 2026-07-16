# IIR biquad

`LiteDSPIIRBiquad` — `litedsp.filter.iir_biquad` — category `filter`

latency: 2 samples · CSR: no · bypass: yes

## Overview

One DF2T biquad section applied to I and Q with shared coefficients.

``coefficients`` is a dict ``{b0,b1,b2,a1,a2}`` of signed integers in Q?.``frac_bits``
(a1,a2 are the *denominator* taps; a0 is normalized to 1).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coefficients` | — | none | Coefficient list (signed integers, quantized via litedsp.filter.design). |
| `frac_bits` | `14` | int | Fractional bits of the coefficient/control fixed-point format. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 1722 | 834 | 0 | 24 | 57.2 |
| xilinx | 218 | 35 | 0 | 36 | 83.5 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).
