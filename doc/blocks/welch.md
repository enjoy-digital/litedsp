# Welch PSD

`LiteDSPWelchPSD` — `litedsp.analysis.welch` — category `analysis`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Windowed, averaged power spectral density: Window -> FFT -> PSD, with segment overlap.

Applies a window before the FFT (reducing spectral leakage vs a bare PSD) and averages
``2**avg_log2`` segments. Output is the averaged spectrum in natural bin order. With
``overlap`` > 0, successive ``N``-sample segments share ``N*overlap/100`` samples (the
Welch method proper): the shared tail of each segment is replayed from an internal history
RAM into the Window -> FFT -> PSD chain, recovering the variance lost to window tapering
for a given input length.

The replay runs at fabric clock while the input stalls, so the sustained input rate is
bounded by roughly ``f_clk * (1 - overlap/100)`` (each ``N``-sample segment is followed by
``N*overlap/100`` replay cycles; PSD readout stalls add on top). ``overlap=0`` (the
default) keeps the chain fully streaming and is bit-compatible with the non-overlapped
implementation.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `N` | `64` | int | Transform size (power of two). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `avg_log2` | `2` | int | Windowed FFT segments averaged per emitted spectrum, as a power of two (``2**avg_log2``); more averaging lowers the variance of the estimate but lengthens the update interval. |
| `window` | `"hann"` | str | Window function (rect/hann/hamming/blackman). Choices: `hann`, `hamming`, `blackman`, `rect`. |
| `overlap` | `0` | int | Segment overlap in percent (0, 25, 50 or 75); successive segments share ``N*overlap/100`` samples, which must be an integer. Higher overlap yields more segments (lower variance) from the same input length, at the cost of input throughput (see above). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `psd_control` (read-write, 9 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `mode` | `0` | Per-bin combining mode. ``0b00``: Linear average (sum 2**avg_log2 frames, emit sum >> avg_log2).; ``0b01``: Exponential average (acc += (inst - acc) >> avg_log2, persists).; ``0b10``: Max-hold (per-bin peak, persists until cleared).; ``0b11``: Min-hold (per-bin floor, persists until cleared). |
| `[8]` | `clear` | `0` | Restart combining: re-initialize the accumulator at the next frame boundary. (pulse) |

### `psd_status` (read-only, 8 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `avg_log2` | `0` | Averaging exponent (frames = 2**avg_log2). |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_welch.py` (bit-exact/SNR under randomized backpressure).
