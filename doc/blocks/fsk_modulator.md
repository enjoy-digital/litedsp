# FSK / GFSK modulator

`LiteDSPFSKModulator` — `litedsp.comm.fsk_mod` — category `comm`

latency: 6 samples · CSR: yes · bypass: no

## Overview

M-ary FSK (2^bits_per_symbol levels) at ``sps`` samples per symbol, optionally Gaussian
filtered (``bt``, ``span`` symbols: GFSK / GMSK), then frequency modulated.

A symbol ``s`` becomes the level ``l = 2 s - (L - 1)`` scaled to ``l * 2**(dw-1-bps)``, held
for ``sps`` samples (the symbol sink accepts one word per ``sps`` output samples), filtered by
a symmetric ``LiteDSPFIRFilter`` from ``gaussian_coefficients`` when ``bt`` is set, and fed to
the FM engine (``phase_inc`` centre, ``deviation`` from ``litedsp.comm.design.fsk_deviation``:
the reset word is ``h = 1`` for FSK and ``h = 0.5`` for GMSK-style Gaussian filtering). Rate
``sps`` outputs per symbol; latency ``1 + fir + 2`` (``fir = 0`` without the filter).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `bits_per_symbol` | `1` | int | Choices: `1`, `2`. |
| `sps` | `4` | int |  |
| `bt` | `0.5` | float |  |
| `span` | `4` | int |  |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |
| `lut_depth` | `1024` | int |  |
| `fir_architecture` | `"classic"` | str | Choices: `classic`, `mac`. |
| `n_macs` | `4` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `phase_inc` (read-write, 32 bits)

Centre phase increment per sample.

### `deviation` (read-write, 32 bits, reset `0x20000000`)

Phase increment at full-scale level (see fsk_deviation).

### `config` (read-only, 13 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[2:0]` | `bits_per_symbol` | `0` | Bits per symbol. |
| `[10:4]` | `sps` | `0` | Samples per symbol. |
| `[12]` | `gaussian` | `0` | Gaussian pulse filter present. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1222 | 481 | 0 | 7 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_fsk_mod.py` (bit-exact/SNR under randomized backpressure).
