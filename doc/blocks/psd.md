# PSD

`LiteDSPPSD` — `litedsp.analysis.psd` — category `analysis`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Power-spectral-density accumulator for a streaming FFT.

Consumes the (bit-reversed, framed) output of :class:`litedsp.analysis.fft.FFT`, combines
``|X[k]|**2 = I**2 + Q**2`` per bin over ``2**avg_log2`` frames, then emits the resulting
spectrum (``N`` values, **natural** bin order, framed with first/last). While emitting, it
backpressures the FFT, so no samples are lost.

The per-bin combining is runtime-selectable (``mode`` Signal / CSR field):

- ``PSD_MODE_LINEAR`` (0, default): sum ``2**avg_log2`` frames, emit ``sum >> avg_log2``;
  the accumulator restarts on each spectrum (today's averaged PSD).
- ``PSD_MODE_EXP`` (1): exponential/leaky average ``acc += (inst - acc) >> avg_log2``;
  the accumulator persists across spectra (continuously tracking display trace).
- ``PSD_MODE_MAX`` (2): per-bin max-hold (captures transients; persists until cleared).
- ``PSD_MODE_MIN`` (3): per-bin min-hold (noise-floor trace; persists until cleared).

A ``clear`` pulse (Signal / CSR field) restarts the combining: the next frame boundary
re-initializes the accumulator (overwrite instead of combine), so max/min/exponential
traces can be reset at runtime. Spectra are emitted every ``2**avg_log2`` frames in all
modes; the emission cadence is not affected by ``clear``.

``fft_latency`` is the upstream FFT pipeline latency (default ``N-1``, matching
:class:`litedsp.analysis.fft.LiteDSPFFT`); the first ``fft_latency`` samples (pipeline
fill) are skipped so frames align.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `N` | `64` | int | Transform size (power of two). |
| `fft_latency` | — | none | Upstream FFT pipeline latency in cycles; that many initial fill samples are discarded so bin 0 aligns with frame start. Defaults to N-1 (LiteDSPFFT). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `avg_log2` | `4` | int | Frames per emitted spectrum, as a power of two (``2**avg_log2``); in linear mode each step adds one bit to the accumulator RAM and output width (power_width), in exponential mode it sets the leak time-constant. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 9 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `mode` | `0` | Per-bin combining mode. ``0b00``: Linear average (sum 2**avg_log2 frames, emit sum >> avg_log2).; ``0b01``: Exponential average (acc += (inst - acc) >> avg_log2, persists).; ``0b10``: Max-hold (per-bin peak, persists until cleared).; ``0b11``: Min-hold (per-bin floor, persists until cleared). |
| `[8]` | `clear` | `0` | Restart combining: re-initialize the accumulator at the next frame boundary. (pulse) |

### `status` (read-only, 8 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `avg_log2` | `0` | Averaging exponent (frames = 2**avg_log2). |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 864 | 32 | 0 | 2 | 90.3 |
| xilinx | 343 | 30 | 0 | 2 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_psd.py` (bit-exact/SNR under randomized backpressure).
