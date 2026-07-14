# Decimator

`LiteDSPDecimator` — `litedsp.rate.decimator` — category `rate`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Integer decimator: anti-alias filter + rate drop.

``method="cic"`` (default) uses a portable CIC (efficient for large factors); ``method="fir"``
uses a polyphase decimating FIR with a windowed-sinc low-pass (cleaner passband).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `decimation` | `8` | int | Integer decimation factor. |
| `method` | `"cic"` | str | Core implementation selector. Choices: `cic`, `fir`. |
| `n_taps` | — | none | Number of FIR taps. |
| `cutoff` | `0.4` | float | Anti-alias low-pass cutoff, normalized to the output (decimated) sample rate (0..0.5); used by ``method="fir"`` only (the CIC response is fixed by its structure). |
| `n_stages` | `4` | int | Number of CIC integrator/comb stages (N in the literature). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `core_config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `rate` | `0` | Decimation factor R. |
| `[23:16]` | `stages` | `0` | CIC stages N. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
