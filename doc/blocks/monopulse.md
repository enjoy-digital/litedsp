# Monopulse angle

`LiteDSPMonopulse` — `litedsp.radar.beamform` — category `radar`

latency: 21 samples · CSR: yes · bypass: no

## Overview

Phase-comparison monopulse: the phase of ``a * conj(b)`` for two element / sub-array
streams.

``sink_a`` and ``sink_b`` (I/Q, joined) feed a :class:`LiteDSPMixer` in down-conversion mode
(``a * conj(b)``, rounded to ``data_width``) and a vectoring :class:`LiteDSPCORDIC` gives the
angle on :func:`~litedsp.common.angle_layout` (full circle = ``2**angle_width``); the
``first`` / ``last`` tags of ``sink_a`` are carried through a FIFO join. The angle of arrival
follows from the phase, the element spacing and the wavelength on the host. Latency
``2 + cordic.latency``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `angle_width` | `16` | int |  |
| `stages` | — | none |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink_a` | sink | iq |
| `sink_b` | sink | iq |
| `source` | source | angle |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 16 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[5:0]` | `angle_width` | `0` | Angle word width (full circle = 2^angle_width). |
| `[15:8]` | `latency` | `0` | Pipeline latency in cycles. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1934 | 958 | 0 | 4 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
