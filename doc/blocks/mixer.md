# Mixer (complex)

`LiteDSPMixer` — `litedsp.mixing.mixer` — category `mixing`

latency: 2 samples · CSR: yes · bypass: yes

## Overview

Complex mixer with runtime up/down mode and bypass.

Multiplies two complex I/Q streams ``sink_a`` and ``sink_b`` and outputs the rescaled
result on ``source``. ``mode`` selects up- or down-conversion at runtime (not build time).
The full-precision product is rescaled with round-half-up + saturation (no silent
truncation/overflow). Both sinks are consumed together; ``source`` is produced after a
fixed 2-cycle latency.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink_a` | sink | iq |
| `sink_b` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 10 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `mode` | `0` |  ``0b0``: Down-conversion (a * conj(b)).; ``0b1``: Up-conversion (a * b). |
| `[9:8]` | `bypass` | `0` |  ``0b00``: Bypass disabled (mix).; ``0b01``: Pass Sink A to Source.; ``0b10``: Pass Sink B to Source. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 380 | 296 | 0 | 4 | 272.5 | — |
| xilinx | 109 | 130 | 0 | 4 | 226.3 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_mixer.py` (bit-exact/SNR under randomized backpressure).
