# IIR biquad

`LiteDSPIIRBiquad` — `litedsp.filter.iir_biquad` — category `filter`

latency: 2 samples · CSR: no · bypass: yes

## Overview

One DF2T biquad section applied to I and Q with shared coefficients.

``coefficients`` is a dict ``{b0,b1,b2,a1,a2}`` of signed integers in Q?.``frac_bits``
(a1,a2 are the *denominator* taps; a0 is normalized to 1).

``architecture="classic"`` accepts one sample per clock. ``"folded"`` divides the
feedback recurrence into feed-forward/y, feedback-product, and state-update cycles. It
accepts one sample every three clocks, uses two extra cycles of latency, and is
bit-identical to classic mode. The bypass value is sampled with each folded input.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coefficients` | — | none | Coefficient list (signed integers, quantized via litedsp.filter.design). |
| `frac_bits` | `14` | int | Fractional bits of the coefficient/control fixed-point format. |
| `architecture` | `"classic"` | str | Choices: `classic`, `folded`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1722 | 834 | 0 | 24 | 57.2 | — |
| xilinx | 218 | 35 | 0 | 36 | 83.5 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
