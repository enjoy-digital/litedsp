# Pulse compressor (chirp matched filter)

`LiteDSPPulseCompressor` — `litedsp.radar.compress` — category `radar`

latency: 4 samples · CSR: yes · bypass: no

## Overview

Matched filter for the linear-FM pulse of :class:`~litedsp.generation.source.LiteDSPChirp`
(``pulse_len`` samples sweeping ``bandwidth`` cycles/sample), i.e. the correlation of the
received I/Q stream with the conjugate time-reversed (optionally tapered) reference.

The complex-tap convolution runs on two :class:`~litedsp.filter.fir.LiteDSPFIRFilterComplex`
in lock-step (real taps ``Re h`` and ``Im h`` applied to I and Q) and is recombined as
``y = (re.i - im.q) + j (re.q + im.i)`` with saturation. ``shift`` rescales the
``pulse_len``-fold coherent gain (default ``data_width - 1 + log2(pulse_len)``: a full-scale
echo peaks near full scale). ``first``/``last`` are re-aligned by ``pulse_len - 1`` beats so
range bin ``r`` of a pulse sits at position ``r`` of the output frame (the first
``pulse_len - 1`` positions of a frame carry the fold-over of the previous one). Latency
``fir.latency + 1`` (``None``, variable, with the serial ``mac`` architecture).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `pulse_len` | `16` | int |  |
| `bandwidth` | `0.5` | float |  |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `window` | `"rect"` | str | Taper of the reference (``rect``, ``hann``, ``hamming``, ``blackman``): lower range sidelobes for a wider main lobe. Choices: `rect`, `hann`, `hamming`, `blackman`. |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |
| `lut_depth` | `1024` | int |  |
| `fir_architecture` | `"classic"` | str | Choices: `classic`, `pipelined`, `mac`. |
| `n_macs` | `4` | int |  |

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
| `[15:0]` | `pulse_len` | `0` | Reference length (taps). |
| `[23:16]` | `shift` | `0` | Output rescale shift. |

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the saturation flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `saturated` | `0` | Sticky: an output saturated. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 4236 | 3018 | 0 | 60 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).
