# Corner turn (fast to slow time)

`LiteDSPCornerTurn` — `litedsp.radar.corner_turn` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Transpose a CPI of ``n_pulses`` framed pulses (``n_range_bins`` beats each) into
``n_range_bins`` slow-time columns of ``n_pulses`` beats (the input of the Doppler
processor).

The block-transpose engine of the interleavers (``rows = n_pulses``, ``cols = n_range_bins``,
ping-pong RAM of two CPIs) is fed in arrival order, so throughput is one sample per cycle
once the first CPI has filled; the output is framed per column (``first`` on pulse 0,
``last`` on pulse ``n_pulses - 1``). Input framing is checked against the arrival position:
a misplaced ``first`` or ``last`` sets the sticky ``frame_error`` (``clear`` resets it) — the
transpose itself counts from reset. ``latency = None`` (a CPI is buffered).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_range_bins` | `64` | int |  |
| `n_pulses` | `16` | int |  |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

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
| `[15:0]` | `n_range_bins` | `0` | Range bins per pulse. |
| `[31:16]` | `n_pulses` | `0` | Pulses per CPI. |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the frame error. (pulse) |

### `status` (read-only, 10 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `frame_error` | `0` | Sticky: input framing did not match the CPI geometry. |
| `[9:8]` | `filled` | `0` | CPIs buffered (0..2). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 138 | 135 | 4 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_corner_turn.py` (bit-exact/SNR under randomized backpressure).
