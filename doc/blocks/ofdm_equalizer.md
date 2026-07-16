# OFDM equalizer (1-tap)

`LiteDSPOFDMEqualizer` — `litedsp.comm.ofdm_eq` — category `comm`

latency: 2 samples · CSR: yes · bypass: no

## Overview

LS channel estimation + divider-free one-tap OFDM equalizer with per-bin CSI.

Pulse ``train`` (Signal, or the CSR ``control.train``): the **next full frame** is
consumed as the preamble (no output) and ``H_k = scaled(Y_k * conj(X_ref_k), 1)`` is
stored per bin; subsequent frames are equalized as ``S_k = scaled(Y_k * conj(H_k),
coeff_frac)`` with ``|H_k|**2`` (same ``coeff_frac`` scaling) on the ``csi`` source
param field. There is no divider: hard-decision users see a per-bin gain/phase-corrected
constellation up to the (positive, real) ``|H_k|**2`` scaling — phase is exact, QPSK
signs are unaffected, and amplitude-sensitive consumers normalize by ``csi`` (the
standard CSI-weighted soft-demapping formulation).

The 2-bit-per-bin reference RAM holds the preamble's QPSK signs (bit 0 = I, bit 1 = Q,
``1`` = positive: ``X_ref_k = (+/-1) + j*(+/-1)``), reset to ``1 + 1j`` on every bin and
runtime-loadable through ``ref_data``/``ref_we``/``ref_rst`` (sequential write, like the
FIR coefficient reload). ``H`` is signed Q(data_width-coeff_frac).``coeff_frac`` per
component and resets to ``1.0 + 0j`` on every bin, so the untrained block is a unit-gain
passthrough (``csi = 1.0``); with a preamble axis amplitude of ``2**coeff_frac`` LSBs and
a flat channel it re-estimates to 1.0.

Frames are ``fft_size`` beats, counted from the first sample after reset (align upstream
— CP remove / FFT — before this block, as with the CP blocks); ``first``/``last`` are
(re)generated from the position counter. Bins are addressed by frame position for both
estimation and equalization, so bit-reversed FFT order needs no reorder — only the
reference must be loaded in the same order. Downstream sinks without a ``csi`` field
connect with ``connect(..., omit={"csi"})``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `fft_size` | `64` | int | OFDM symbol length N in bins per frame; sets the H/reference RAM depths. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coeff_frac` | `14` | int | Fractional bits of the stored channel estimate H (signed Q(data_width-coeff_frac).coeff_frac, 1.0 = 2**coeff_frac); also the rescale shift of the equalized output and of the csi field (1 <= coeff_frac <= data_width - 1). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 24 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `fft_size` | `0` | Bins per frame N. |
| `[23:16]` | `coeff_frac` | `0` | Fractional bits of H (1.0 = 2**coeff_frac). |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `train` | `0` | Train: consume the next full frame as the known preamble and store H_k = Y_k * conj(X_ref_k) per bin (no output for that frame). (pulse) |

### `ref_reset` (read-write, 1 bit)

Reset the reference write pointer to bin 0 (write to strobe).

### `ref` (read-write, 2 bits)

Write the next bin's 2-bit preamble reference (bit 0 = I sign, bit 1 = Q sign, 1 = positive; auto-incrementing bin index).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 547 | 128 | 0 | 6 | 95.1 |
| xilinx | 310 | 68 | 0 | 6 | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_ofdm_eq.py` (bit-exact/SNR under randomized backpressure).
