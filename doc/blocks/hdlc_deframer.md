# HDLC deframer

`LiteDSPHDLCDeframer` — `litedsp.comm.hdlc` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

HDLC bit stream to payload bits: flag detection, unstuffing, the X.25 FCS check.

Accepted bits (payload + FCS + the closing flag's first seven bits, stuffed zeros dropped)
enter a 24-bit pending register; a bit leaves once 24 newer ones have arrived, so the FCS
and flag-prefix bits never leave and the closing flag releases the last payload bit with
``last`` and the FCS verdict ``fcs_ok`` on it (the CRC runs seven bits behind the newest,
covering exactly payload + FCS). Frames without payload (idle flags) are ignored, an abort
(seven ones) drops the frame.
Status: ``fcs_ok`` (last frame), ``frames``, ``fcs_errors``, ``aborts``, sticky
``fcs_error``, ``clear``. ``latency = None``.

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | raw |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the FCS error flag. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `fcs_ok` | `0` | The last frame's FCS matched. |
| `[1]` | `fcs_error` | `0` | Sticky: a frame failed its FCS. |

### `frames` (read-only, 32 bits)

Frames received.

### `fcs_errors` (read-only, 32 bits)

FCS failures.

### `aborts` (read-only, 32 bits)

Aborted frames.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 221 | 170 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_hdlc.py` (bit-exact/SNR under randomized backpressure).
