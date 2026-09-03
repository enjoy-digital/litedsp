# SSB modulator

`LiteDSPSSBModulator` — `litedsp.comm.ssb_mod` — category `comm`

latency: 3 samples · CSR: yes · bypass: no

## Overview

SSB by the phasing method: ``s = x + j * sgn * hilbert(x)`` on a complex baseband
(``sideband`` runtime: 0 upper, 1 lower), the Q path negated with saturation for LSB. Feed a
DUC for the RF carrier. Latency = the Hilbert filter's (``n_taps`` odd, ``(n_taps - 1) / 2``
group delay on the I path). Opposite-sideband rejection is set by the Hilbert length
(~40 dB with 31 taps away from DC).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_taps` | `31` | int | Number of FIR taps. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `sideband` | `0` | 0: upper sideband, 1: lower sideband. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1118 | 1230 | 0 | 17 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
