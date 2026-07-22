# FIR interpolator

`LiteDSPFIRInterpolator` — `litedsp.filter.fir_poly` — category `filter`

latency: 32 samples · CSR: yes · bypass: no

## Overview

Interpolate-by-L complex FIR with a single time-shared MAC per I/Q (polyphase).

For each input it emits L outputs, output ``p`` computed from polyphase sub-filter
``c[p::L]`` over the recent inputs (``y[nL+p] = sum_k c[p+kL]·x[n-k]``), round + saturate.

``architecture="classic"`` performs the multiply and accumulator update in one clock.
``architecture="pipelined"`` registers both the asynchronous RAM operands and the product,
then drains those two stages in two additional clocks per output. This keeps the same
two-multiplier serial-MAC area and bit-exact output sequence while separating address/read,
multiply, and accumulator-feedback paths.

``prune_zeros=True`` builds a compact, phase-specific MAC schedule from the non-zero
build-time taps. Every phase must retain at least one tap. This is intended for structurally
sparse filters such as half-band rate changers.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `32` | int | Number of FIR taps. |
| `interpolation` | `8` | int | Integer interpolation factor. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coefficients` | — | none | Coefficient list (signed integers, quantized via litedsp.filter.design). |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |
| `architecture` | `"classic"` | str | Implementation architecture selector; timing variants publish latency/throughput trade-offs. Choices: `classic`, `pipelined`. |
| `prune_zeros` | `False` | bool |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `taps` | `0` | FIR taps N. |
| `[31:16]` | `rate` | `0` | Interpolation factor L. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 336 | 86 | 0 | 2 | 109.4 | — |
| xilinx | 195 | 60 | 0 | 2 | — | — |
| xilinx_au | 152 | 60 | 0 | 2 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_fir_poly.py` (bit-exact/SNR under randomized backpressure).
