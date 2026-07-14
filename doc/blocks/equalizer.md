# LMS equalizer

`LiteDSPLMSEqualizer` — `litedsp.filter.equalizer` — category `filter`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Adaptive complex FIR equalizer (LMS), trained or decision-directed.

Filters ``x`` with ``n_taps`` complex weights and adapts them to minimize ``|d - y|``:
``w_k += mu * e * conj(x[n-k])`` with ``e = d - y``. The sink carries both the input
(``i``,``q``) and the desired symbol (``d_i``,``d_q``); drive ``train`` low to freeze the
weights (feed a slicer's decision back as ``d`` for decision-directed operation). ``mu_shift``
sets the (inverse) step size; weights are Q.``wfrac`` with the center tap initialized to 1.0.

Adaptation is *delayed LMS* (the standard hardware form): the update applies the previous
sample's error (registered with its input-window snapshot), so the filter and the update
each carry one multiply level per cycle instead of chaining y -> e -> update
combinationally. Convergence is indistinguishable at practical step sizes.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `7` | int | Number of FIR taps. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `wfrac` | `14` | int | Fractional bits of each complex weight (signed Q``wint``.``wfrac``); the center tap is initialized to 1.0 = 2**wfrac. More bits = finer adaptation steps. |
| `wint` | `4` | int | Integer bits of each weight; bounds the weight magnitude (updates saturate). Keep wint + wfrac <= 18 so each weight*sample product fits one 18x18 DSP block. |
| `mu_shift` | `20` | int | LMS step-size exponent, mu = 2**-mu_shift (update uses a bare right shift). Larger = slower but more stable convergence with lower steady-state misadjustment. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `train` (read-write, 1 bit, reset `0x1`)

Enable LMS adaptation.

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_equalizer.py` (bit-exact/SNR under randomized backpressure).
