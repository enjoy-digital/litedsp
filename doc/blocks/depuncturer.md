# Depuncturer (LLR)

`LiteDSPDepuncturer` — `litedsp.comm.puncture` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

RX depuncturer: reassembles full soft symbols, reinserting erasures (LLR 0) per pattern.

One signed ``llr_bits`` LLR in per beat (the puncturer's serial kept-bit order, e.g. from
the soft demapper), one packed n-slot LLR symbol out per pattern column — slot ``j`` at
bits ``[j*llr_bits +: llr_bits]``, LLR 0 at punctured slots — feeding the soft
:class:`~litedsp.comm.viterbi.LiteDSPViterbiDecoder` (``llr_bits`` set) directly.
Variable rate (``latency = None``): a column consumes as many input beats as it keeps.
``phase_rst`` (CSR pulse) re-zeros the pattern phase and drops any partially assembled
symbol (block-boundary alignment).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `pattern` | `[[1, 0, 1], [1, 1, 0]]` | list | Puncturing matrix, matching the transmitter's (see the module-level DVB-S constants). Every column must keep at least one bit. Default: ``PUNCTURE_1_2``. |
| `n` | `2` | int | Coded bits per output symbol (the mother code's 1/n rate). |
| `llr_bits` | `4` | int | Width of each signed LLR (matching the soft demapper/decoder). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | raw |
| `source` | source | raw |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `phase_rst` | `0` | Re-zero the pattern phase and drop any partially assembled symbol. (pulse) |

### `config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `period` | `0` | Puncturing pattern period (columns). |
| `[15:8]` | `n` | `0` | Coded bits per output symbol (mother code 1/n). |
| `[23:16]` | `llr_bits` | `0` | Signed LLR width. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 31 | 16 | 0 | 0 | 474.3 | — |
| xilinx | 12 | 16 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_puncture.py` (bit-exact/SNR under randomized backpressure).
