# Rational resampler

`LiteDSPRationalResampler` — `litedsp.filter.resampler` — category `filter`

latency: variable (data-dependent) · CSR: no · bypass: no

## Overview

Resample by ``L/M``: polyphase interpolate-by-L then decimate-by-M.

The shared anti-alias/anti-image low-pass runs at the interpolated rate (cutoff set by the
larger of L, M). Built from the polyphase FIRs. For arbitrary (non-rational) ratios use the
Farrow interpolator with a phase accumulator instead.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `interpolation` | `3` | int | Integer interpolation factor. |
| `decimation` | `2` | int | Integer decimation factor. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_taps` | — | none | Number of FIR taps. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_resampler.py` (bit-exact/SNR under randomized backpressure).
