# I/Q balance

`LiteDSPIQBalance` — `litedsp.correction.iq_balance` — category `correction`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Correct I/Q gain & phase imbalance with a 2x2 matrix, plus an estimator for calibration.

Datapath: ``I' = I``, ``Q' = (c1*I + c2*Q) >> frac`` (round + saturate). The defaults
(c1=0, c2=1.0) pass through. Estimator accumulators ``E[I^2], E[Q^2], E[I*Q]`` over a
window are exposed (status) so firmware can compute c1, c2 (Gram-Schmidt) — keeping the
divide/sqrt off the datapath (portable, cheap).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coeff_frac` | `14` | int | Fractional bits of the c1/c2 correction coefficients (1.0 = 2**coeff_frac, the c2 reset); sets the gain/phase correction resolution within data_width-bit coefficients. |
| `window_log2` | `14` | int | log2 of the estimator window in samples: the E[I^2]/E[Q^2]/E[I*Q] sums are latched every 2**window_log2 samples; adds window_log2 bits to each accumulator. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

### `c1` (read-write, 16 bits)

Correction coeff c1 (Q?.frac).

### `c2` (read-write, 16 bits, reset `0x4000`)

Correction coeff c2 (Q?.frac).

### `acc_ii` (read-only, 46 bits)

Sum I^2 (last window).

### `acc_qq` (read-only, 46 bits)

Sum Q^2 (last window).

### `acc_iq` (read-only, 46 bits)

Sum I*Q (last window).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).
