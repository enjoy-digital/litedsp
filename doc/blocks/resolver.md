# Resolver-to-digital

`LiteDSPResolverDigital` — `litedsp.motor.resolver` — category `motor`

latency: 21 samples · CSR: yes · bypass: no

## Overview

Resolver-to-digital converter: excitation output, synchronous demodulation, tracking loop.

The excitation sine (``source_exc``, one sample per accepted input, period ``decimation``
samples -- ``f_exc = f_s/decimation``) drives the resolver primary; the ADCs sample the sine
and cosine windings (``sink``: i = sine, q = cosine) at the same rate. Each winding is
multiplied by the reference delayed by ``phase_offset`` samples (analog loop delay) and
integrated exactly over one excitation period (a boxcar of ``decimation`` samples cancels
the carrier ripple), the two sums are vectored by a CORDIC (``atan2(sin_sum, cos_sum)``)
and the resulting raw angle, one per period (rate ``1/decimation``), is smoothed by an
internal :class:`LiteDSPAngleTracker` (``source``, ``speed``). Setting ``phase_offset`` is
the only calibration: a wrong offset lowers the demodulated amplitude (``raw_mag``
status) without biasing the angle.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `angle_width` | `16` | int | Output angle width (full turn = 2**angle_width). |
| `decimation` | `32` | int | Excitation period in input samples (>= 4, ROM depth). |
| `kp_shift` | `3` | int |  |
| `ki_shift` | `8` | int |  |
| `frac_bits` | `14` | int | Tracking-loop fractional bits. |
| `stages` | — | none | CORDIC iterations (defaults to ``angle_width``). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | angle |
| `source_exc` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `phase_offset` (read-write, 5 bits)

Demodulation phase delay in samples (analog loop delay calibration).

### `gains` (read-write, 13 bits, reset `0x803`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `kp_shift` | `3` | Tracking-loop proportional shift. |
| `[12:8]` | `ki_shift` | `8` | Tracking-loop integral shift. |

### `speed` (read-only, 32 bits)

Tracked speed (angle units per excitation period, Q.frac_bits).

### `raw_angle` (read-only, 16 bits)

Last demodulated angle.

### `raw_mag` (read-only, 37 bits)

Demodulated amplitude (maximize with phase_offset).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 5509 | 1825 | 0 | 5 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_resolver.py` (bit-exact/SNR under randomized backpressure).
