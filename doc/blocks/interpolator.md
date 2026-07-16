# Interpolator

`LiteDSPInterpolator` — `litedsp.rate.interpolator` — category `rate`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Integer interpolator: rate expand + anti-image filter.

``method="cic"`` (default) uses a portable CIC; ``method="fir"`` uses a polyphase
interpolating FIR with a windowed-sinc low-pass (gain ``L`` to offset zero-stuff loss).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `interpolation` | `8` | int | Integer interpolation factor. |
| `method` | `"cic"` | str | Core implementation selector. Choices: `cic`, `fir`. |
| `n_taps` | — | none | Number of FIR taps. |
| `cutoff` | `0.4` | float | Anti-image low-pass cutoff, normalized to the input (low) sample rate (0..0.5); used by ``method="fir"`` only (the CIC response is fixed by its structure). |
| `n_stages` | `4` | int | Number of CIC integrator/comb stages (N in the literature). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `core_config` (read-only, 25 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `rate` | `0` | Interpolation factor R. |
| `[23:16]` | `stages` | `0` | CIC stages N. |
| `[24]` | `staged` | `0` | One when the registered-stage architecture is selected. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
