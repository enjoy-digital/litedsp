# HDLC framer

`LiteDSPHDLCFramer` — `litedsp.comm.hdlc` — category `comm`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Payload bits (LSB first, framed by ``last``) to an HDLC bit stream: ``preamble`` opening
flags, the bit-stuffed payload and its X.25 FCS (16 bits, inverted, LSB first), a closing
flag; ``first`` marks the first flag bit, ``last`` the closing flag's last bit. The source
idles between frames. ``latency = None``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `preamble` | `1` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `frames` (read-only, 32 bits)

Frames sent.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 188 | 63 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_hdlc.py` (bit-exact/SNR under randomized backpressure).
