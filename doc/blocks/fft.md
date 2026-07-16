# FFT (SDF)

`LiteDSPFFT` — `litedsp.analysis.fft` — category `analysis`

latency: 63 samples · CSR: yes · bypass: no

## Overview

Streaming radix-2 SDF FFT, ``N`` points (power of two), 1 sample/cycle.

Cascades ``log2(N)`` :class:`LiteDSPFFTStage`s. Output is in **bit-reversed** order (use
:func:`bit_reverse` to reorder), scaled per ``scaling`` below. ``self.latency`` is the
cycles from the first input sample of a frame to its first output sample.

With ``scaling="bfp"`` each stage decides its 1/2 scaling per frame (from the previous
frame's guard-bit occupancy, see :class:`LiteDSPFFTStage`) and the source endpoint gains a
5-bit ``exp`` **param** field (constant across each output frame, like ``first``/``last``
it travels beat-aligned with the payload) carrying the total number of halvings applied:
``output = DFT(x) / 2**exp`` up to fixed-point rounding/saturation, with
``exp in [0, log2(N)]`` (``exp == log2(N)`` reproduces "scaled"-mode arithmetic
bit-exactly). Small signals keep up to ``log2(N)`` extra amplitude bits (~6 dB each).
Downstream analysis blocks (PSD/magnitude) ignore param fields and consume BFP frames
unnormalized; exp-aware consumption lands with the SSR/consumer work — until then,
connect a BFP source to exp-less sinks with ``connect(..., omit={"exp"})``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `N` | `64` | int | Transform size (power of two). |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `twiddle_width` | `16` | int | Twiddle-factor width in bits (signed Q1.(W-1)); sets the per-stage twiddle ROM width, the complex-multiplier size, and the coefficient-quantization noise floor. |
| `inverse` | `False` | bool | Compute the inverse FFT (conjugated, exp(+j) twiddles); output remains 1/N-scaled. |
| `scaling` | `"scaled"` | str | Output scaling. ``"scaled"`` (default): unconditional 1/2 per stage (1/N overall). ``"bfp"``: block floating point — per-frame conditional scaling, per-frame exponent on a 5-bit ``exp`` source param field (see overview above). Choices: `scaled`, `bfp`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `latency` (read-only, 32 bits, reset `0x3f`)

FFT pipeline latency (cycles from frame start to first output).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 4387 | 360 | 0 | 28 | 49.9 | — |
| xilinx | 1885 | 367 | 0 | 28 | 73.2 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_fft.py` (bit-exact/SNR under randomized backpressure).
