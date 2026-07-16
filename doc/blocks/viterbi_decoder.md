# Viterbi decoder

`LiteDSPViterbiDecoder` — `litedsp.comm.viterbi` — category `comm`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Hard/soft-decision Viterbi decoder (rate 1/n, register-exchange survivors).

Hard mode (``llr_bits=None``): ``sink.data`` carries the n coded bits of one symbol and
the branch metric is the Hamming distance. Soft mode (``llr_bits=k``): ``sink.llrs``
carries n packed signed k-bit LLRs (slot ``j`` at bits ``[j*k +: k]`` for coded stream
``polys[j]``, positive = bit 0 more likely — the soft demapper's convention) and the
branch metric is the max-log metric: sum over the coded bits of ``|llr_j|`` where the
LLR sign disagrees with the expected bit (0 where it agrees; an erased/punctured LLR of
0 is free for both hypotheses). With constant-magnitude (e.g. saturated) LLRs this
reduces to a scaled Hamming distance, so decisions match the hard decoder exactly.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `constraint` | `7` | int | Constraint length K, matching the encoder's; the fully-parallel ACS spans 2**(K-1) states, so resources grow exponentially with K. |
| `polys` | `(121, 91)` | list | Generator polynomials, octal, matching the encoder's (rate 1/len(polys); default (0o171, 0o133): the CCSDS/Voyager K=7 pair). |
| `traceback` | — | none | Register-exchange survivor depth in symbols = decoding delay (default 8*K, well past the ~5K convergence rule of thumb); each state keeps a traceback-bit register. |
| `llr_bits` | — | none | None for hard-decision input; k for soft-decision input (n packed signed k-bit LLRs on ``sink.llrs``). |
| `metric_width` | — | none | Path-metric register width in bits. With per-step min-normalization the stored spread is bounded by (K-1)*bm_max (any state is reachable from the current-minimum state in K-1 transitions of at most bm_max = n hard / n*2**(llr_bits-1) soft each), and the reset penalty 2**(metric_width-2) must dominate that spread, so metric_width >= bits((K-1)*bm_max) + 2 (checked). Default: 10 hard (unchanged), max(10, bits((K-1)*bm_max) + 2) soft. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `constraint` | `0` | Constraint length K. |
| `[23:8]` | `traceback` | `0` | Survivor depth (decoding delay). |
| `[31:24]` | `llr_bits` | `0` | Soft-input LLR width (0 = hard-decision input). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 9885 | 3945 | 0 | 0 | 34.3 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_viterbi.py` (bit-exact/SNR under randomized backpressure).
