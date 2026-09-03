# Doppler processor

`LiteDSPDopplerProcessor` — `litedsp.radar.doppler` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Slow-time columns (``n_pulses`` beats per range bin) to range-Doppler map rows.

Composite of :class:`LiteDSPWindow` (omitted for ``window="rect"``), a scaled radix-2
:class:`LiteDSPFFT` over the pulses, the magnitude stage (``"approx"``: alpha-max-beta-min,
``data_width + 1`` bits; ``"power"``: ``i^2 + q^2``, ``2*data_width + 1`` bits) and
:class:`LiteDSPBitReverse`, so each output frame holds the ``n_pulses`` Doppler bins of one
range bin in natural FFT order (bins ``>= n_pulses/2`` are negative velocities). Frame
alignment counts from reset (the window/FFT convention); a ``first``/``last`` arriving at
the wrong position sets the sticky ``frame_error``. ``latency = None`` (a column is
buffered in the reorder).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_pulses` | `16` | int |  |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `window` | `"hann"` | str | Window function (rect/hann/hamming/blackman). Choices: `rect`, `hann`, `hamming`, `blackman`. |
| `magnitude` | `"approx"` | str | Choices: `approx`, `power`. |
| `twiddle_width` | `16` | int |  |
| `beta_shift` | `2` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 25 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `n_pulses` | `0` | Doppler bins (pulses per CPI). |
| `[23:16]` | `out_width` | `0` | Output cell width. |
| `[24]` | `power` | `0` | 1: power cells, 0: magnitude cells. |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the frame error. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `frame_error` | `0` | Sticky: input framing did not match n_pulses. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1768 | 307 | 0 | 14 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_doppler.py` (bit-exact/SNR under randomized backpressure).
