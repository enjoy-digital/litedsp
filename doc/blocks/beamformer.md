# Beamformer

`LiteDSPBeamformer` — `litedsp.radar.beamform` — category `radar`

latency: 3 samples · CSR: yes · bypass: no

## Overview

Narrowband phase-shift beamformer: ``n_elements`` I/Q streams to ``n_beams`` beams.

The element streams are joined (all must present a sample) and each beam is
``y[k] = sum_e w[k][e] * x[e]`` with complex weights in signed Q(2).weight_frac (four real
products per element, an adder tree, then ``scaled(sum, shift, data_width)`` with the
sticky ``saturated`` flag; ``shift`` defaults to ``weight_frac`` so unity weights pass the
element scale). Beams are computed serially, one per cycle (``cycles_per_sample =
n_beams``); with more than one beam the output carries a ``channel`` tag. Weights live in
active / shadow registers: write ``weight_index`` (``beam * n_elements + element``),
``weight_re`` / ``weight_im`` with ``weight_we``, then ``commit`` copies the shadow set
between samples (atomic per sample). Reset weights are the broadside average
(``1 / n_elements``). Latency 3 for a single beam. See
``litedsp.radar.design.steering_weights`` for the host-side steering / taper maths.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_elements` | `4` | int |  |
| `n_beams` | `1` | int |  |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `weight_width` | `16` | int |  |
| `weight_frac` | `14` | int |  |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sinks[0]` | sink | iq |
| `sinks[1]` | sink | iq |
| `sinks[2]` | sink | iq |
| `sinks[3]` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `weight_index` (read-write, 2 bits)

Shadow weight index (beam * n_elements + element).

### `weight` (read-write, 32 bits)

Writing loads the shadow weight at weight_index.

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `re` | `0` | Weight real part (signed Q2.14). |
| `[31:16]` | `im` | `0` | Weight imaginary part. |

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit` | `0` | Copy the shadow weights between samples. (pulse) |
| `[1]` | `clear` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `commit_pending` | `0` | A commit waits for the sample boundary. |
| `[1]` | `saturated` | `0` | Sticky: a beam output saturated. |

### `config` (read-only, 21 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `n_elements` | `0` | Array elements. |
| `[11:8]` | `n_beams` | `0` | Beams per sample. |
| `[20:16]` | `weight_frac` | `0` | Weight fractional bits. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1075 | 678 | 0 | 16 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
