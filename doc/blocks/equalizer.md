# LMS equalizer

`LiteDSPLMSEqualizer` — `litedsp.filter.equalizer` — category `filter`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Adaptive complex FIR equalizer: trained LMS, blind CMA or decision-directed.

Filters ``x`` with ``n_taps`` complex weights and adapts them with the stochastic-gradient
update ``w_k += mu * e * conj(x[n-k])``, where the error ``e`` is selected by the runtime
``mode`` control (``MODE_*``, CSR field of the same values):

- ``0`` trained (default): ``e = d - y``. The sink carries both the input (``i``,``q``)
  and the desired symbol (``d_i``,``d_q``) — a training sequence, or an external slicer's
  decisions fed back as ``d``.
- ``1`` CMA (blind, no reference): ``e = y * (R2 - |y|^2)`` minimizes the constant-modulus
  dispersion ``E[(|y|^2 - R2)^2]``; ``d_i``/``d_q`` are ignored. ``cma_r2`` holds the
  target modulus R2 in the Q-format of ``|y|^2`` rescaled to the sample fractional bits
  (see the error-term section for the derivation): for QPSK at per-axis amplitude ``A``,
  program ``cma_r2 = round(2*A**2 / 2**(data_width-1))``. The per-axis error is saturated
  to the trained-mode error width *before* the ``mu`` shift, bounding the worst-case
  weight step during acquisition (critical for CMA stability).
- ``2`` decision-directed: ``d`` is the nearest QPSK point of ``y``, i.e.
  ``(sign(y_i), sign(y_q)) * dd_level``, and ``e = d - y``; use after blind (CMA)
  acquisition to track with lower misadjustment. ``dd_level`` is the positive per-axis
  decision amplitude.

Drive ``train`` low to freeze adaptation in any mode (weights hold, filtering continues).
``mu_shift`` sets the (inverse) step size; weights are Q.``wfrac`` with the center tap
initialized to 1.0.

Adaptation is *delayed LMS* (the standard hardware form). ``architecture="classic"``
applies the previous sample's registered error/window. ``"pipelined"`` registers the FIR
result, modulus square, and selected error separately and applies it after three accepted
samples. Both retain one-sample-per-clock filter throughput and latency; the latter trades
adaptation-loop delay and registers for a shorter CMA timing cone.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `7` | int | Number of FIR taps. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `wfrac` | `14` | int | Fractional bits of each complex weight (signed Q``wint``.``wfrac``); the center tap is initialized to 1.0 = 2**wfrac. More bits = finer adaptation steps. |
| `wint` | `4` | int | Integer bits of each weight; bounds the weight magnitude (updates saturate). Keep wint + wfrac <= 18 so each weight*sample product fits one 18x18 DSP block. |
| `mu_shift` | `20` | int | LMS step-size exponent, mu = 2**-mu_shift (update uses a bare right shift). Larger = slower but more stable convergence with lower steady-state misadjustment. |
| `cma_egain` | `0` | int | Log2 gain applied to the CMA error before its saturation, e = sat(y * dm * 2**cma_egain) with dm the modulus error R2 - mag(y)^2; other modes are unaffected. The CMA gradient scales as signal power times amplitude, so at operating levels well below full scale it is much smaller than the trained/DD error (~30x at 0.2 of full scale): set cma_egain so both land at a comparable magnitude and a single mu_shift serves blind acquisition and decision-directed tracking (each unit doubles the effective CMA step). 0 keeps the exact derived Q-format. |
| `architecture` | `"classic"` | str | ``"classic"`` for one-sample delayed LMS, or ``"pipelined"`` for a three-sample adaptation delay with unchanged filter throughput/output latency. Choices: `classic`, `pipelined`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `train` (read-write, 1 bit, reset `0x1`)

Enable weight adaptation (0 = freeze: weights hold, filtering continues).

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `mode` | `0` | Error-term select (3 reserved, behaves as trained). 0: trained; 1: cma; 2: dd |

### `cma_r2` (read-write, 17 bits)

CMA target modulus R2, fractional bits = data_width - 1 (QPSK at per-axis amplitude A: round(2*A**2 / 2**(data_width-1))).

### `dd_level` (read-write, 15 bits)

Decision-directed per-axis QPSK decision amplitude (positive).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_equalizer.py` (bit-exact/SNR under randomized backpressure).
