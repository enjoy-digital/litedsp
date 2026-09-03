# Line decoder (NRZI)

`LiteDSPLineDecoder` — `litedsp.comm.line_code` — category `comm`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Line code to bits. NRZI: a bit from each level change (rate 1:1, latency 1). Manchester
codes consume chip pairs (rate 1:2; ``phase_rst`` re-aligns the pair phase): a pair without a
mid-bit transition is a ``violation`` (counted, sticky flag, the bit is taken from the first
chip). ``invert`` flips the input.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `code` | `"nrzi_s"` | str | Choices: `nrzi_s`, `nrzi_m`, `manchester`, `diff_manchester`. |
| `invert` | `False` | bool |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `invert` | `0` | Invert the input. |
| `[1]` | `phase_rst` | `0` | Re-align the chip phase. (pulse) |
| `[2]` | `clear` | `0` | Clear the violation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `violation` | `0` | Sticky: a chip pair without a mid-bit transition. |

### `violations` (read-only, 32 bits)

Violations since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 43 | 39 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_line_code.py` (bit-exact/SNR under randomized backpressure).
