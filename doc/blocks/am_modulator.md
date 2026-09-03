# AM modulator

`LiteDSPAMModulator` — `litedsp.comm.am_mod` — category `comm`

latency: 2 samples · CSR: yes · bypass: no

## Overview

AM modulator: ``envelope = 2**(dw-2) * (1 + m * x)`` with the modulation index ``m``
(unsigned Q1.(dw-1), reset 1.0), a half-scale carrier so ``m <= 1`` never overflows.

``carrier="baseband"``: I = envelope, Q = 0 (feed a DUC), latency 2; ``carrier="nco"``: the
envelope multiplies an internal carrier (``phase_inc`` per sample, quarter-wave ROM), I / Q =
envelope x cos / sin rounded to ``data_width``, latency 4. Loops back through
:class:`~litedsp.comm.am_demod.LiteDSPAMDemod`.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `carrier` | `"baseband"` | str | Choices: `baseband`, `nco`. |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |
| `lut_depth` | `1024` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `index` (read-write, 16 bits, reset `0x8000`)

Modulation index (unsigned Q1.15, 1.0 = 32768).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 770 | 147 | 0 | 3 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_am_mod.py` (bit-exact/SNR under randomized backpressure).
