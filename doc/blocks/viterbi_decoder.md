# Viterbi decoder

`LiteDSPViterbiDecoder` — `litedsp.comm.viterbi` — category `comm`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Hard/soft-decision Viterbi decoder (rate 1/n, selectable survivor architecture).

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
| `decision_memory` | `False` | bool | Store one predecessor-decision row per symbol and use folded synchronous traceback instead of register-exchange survivor paths. Reduces routing/FF pressure but stalls input during traceback and emits one decoded bit per traceback operation. |
| `normalize_interval` | `16` | int | Accepted symbols between metric-normalization cycles in decision-memory mode. The global minimum and subtract are isolated in separate FSM states rather than the ACS feedback path. Nominal ``cycles_per_output`` excludes the one additional normalization clock every ``normalize_interval`` accepted symbols and any downstream backpressure. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 65 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `constraint` | `0` | Constraint length K. |
| `[23:8]` | `traceback` | `0` | Survivor depth (decoding delay). |
| `[31:24]` | `llr_bits` | `0` | Soft-input LLR width (0 = hard-decision input). |
| `[32]` | `decision_memory` | `0` | One for folded RAM-survivor traceback; zero for register exchange. |
| `[48:33]` | `normalize_interval` | `0` | Accepted symbols between metric normalization cycles. |
| `[64:49]` | `cycles_per_output` | `0` | Nominal clocks per decoded output (excludes backpressure). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 6634 | 864 | 2 | 0 | 90.1 | 100.0 |
| xilinx | 4171 | 802 | 1 | 0 | 90.6 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_viterbi.py` (bit-exact/SNR under randomized backpressure).
