# Parametric EQ

`LiteDSPAudioEQ` — `litedsp.audio.eq` — category `audio`

latency: 25 samples · CSR: yes · bypass: yes

## Overview

Multi-band, multi-channel parametric equalizer: a time-multiplexed biquad engine.

``n_bands`` cascaded biquads per channel of the TDM stream share one multiplier: per
beat the engine runs the bands in sequence (8 cycles each) from state and coefficient
RAMs, so ``cycles_per_sample = 8*n_bands + 2`` (a 3-band stereo EQ at 48 kHz needs a
2.5 MHz clock). Each section is direct-form I with a full-precision accumulator and
first- (``error_feedback=1``, default) or second-order error feedback of the rounding
error, i.e. the noise transfer (1 - z^-1)^k cancels the huge low-frequency round-off gain
of low-Q/low-frequency biquads (a 40 Hz shelf at 48 kHz has poles at r = 0.997) while the
state stays narrow (x1, x2, y1, y2 at ``data_width``, e at ``frac_bits``). Coefficients are
signed Q(coeff_width-frac_bits).frac_bits (Q4.28 by default: pole-radius resolution 4e-9,
what 20-50 Hz bands need) per band, shared by the channels; ``sections`` seeds them
(dicts from :func:`litedsp.filter.design.biquad_sos_quantize`, default passthrough).

Runtime reload: write ``coeff_index`` (``8*band + k``, k = 0..4 for b0, b1, b2, a1, a2)
then ``coeff_value`` (auto-incrementing) into a shadow table, and pulse ``commit``: the
engine copies shadow -> active between beats, so no sample sees mixed coefficients.
``band_enable`` bits bypass individual bands (state kept fresh for a click-free
re-enable); ``bypass`` passes beats through (2 cycles). Sticky ``sat`` on output
saturation. Latency ``8*n_bands + 1`` cycles.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_bands` | `3` | int | Cascaded biquad sections per channel. |
| `n_channels` | `2` | int | Channels in the TDM frame (1 = mono, real layout). |
| `coeff_width` | `32` | int |  |
| `frac_bits` | `28` | int | Fractional bits of the coefficient/control fixed-point format. |
| `sections` | — | none | Initial coefficients: ``n_bands`` dicts ``{b0, b1, b2, a1, a2}`` (default passthrough). |
| `error_feedback` | `1` | int | Order of the error feedback (0, 1 or 2). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `n_bands` | `0` | Cascaded sections per channel. |
| `[15:8]` | `n_channels` | `0` | Channels in the TDM frame. |
| `[23:16]` | `coeff_width` | `0` | Coefficient width in bits. |
| `[31:24]` | `frac_bits` | `0` | Coefficient fractional bits. |

### `coeff_index` (read-write, 5 bits)

Shadow coefficient address: 8*band + k (k = 0..4: b0, b1, b2, a1, a2); auto-increments on value writes.

### `coeff_value` (read-write, 32 bits)

Shadow coefficient value (signed Q(coeff_width-frac_bits).frac_bits); writing stores and increments the index.

### `band_enable` (read-write, 3 bits, reset `0x7`)

Per-band enable mask (a disabled band passes its input through).

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit` | `0` | Copy the shadow coefficients into the active set. (pulse) |
| `[1]` | `bypass` | `0` | Pass beats through unchanged. |
| `[2]` | `clear_sat` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit_pending` | `0` | A commit is waiting for the engine. |
| `[1]` | `saturation` | `0` | A band output saturated since the last clear. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 777 | 160 | 0 | 4 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
