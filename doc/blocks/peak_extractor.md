# Peak extractor

`LiteDSPPeakExtractor` — `litedsp.radar.detect` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Detected cells to sparse target records with sub-bin centroids.

Consumes a CFAR map (``n_range_bins`` rows of ``n_doppler_bins`` cells on
:func:`~litedsp.common.cell_layout`, rows counted from reset) through two line buffers so
each cell is seen with its 3x3 neighbourhood (zero padded). A detected cell becomes a
record when ``local_max`` is clear, or when it is a strict maximum over its raster-earlier
neighbours and no smaller than the later ones (a plateau yields exactly one record). With
``interpolate`` the parabolic sub-bin offset along each axis,
``(y_next - y_prev) / (2 * (2 y0 - y_prev - y_next))`` in Q.frac_bits, is computed by a
bit-serial divider (``frac_bits + 3`` cycles per record, the input is stalled), clamped to
+/-0.5 bin (0 when the curvature is not negative). Output on
:func:`~litedsp.common.target_layout`: one burst per CPI, records (``hit = 1``, ``range`` and
``doppler`` unsigned Q.frac_bits, ``data`` = the peak cell) closed by a terminator beat
(``hit = 0``, ``data`` = record count, ``last``); the optional ``ev.cpi`` interrupt fires with
the terminator. A misplaced ``first``/``last`` sets the sticky ``frame_error``.
``latency = None``; rate data dependent (one virtual cell per row and one virtual row per
CPI are flushed with ``sink.ready`` low).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_range_bins` | `64` | int |  |
| `n_doppler_bins` | `16` | int |  |
| `data_width` | `17` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `index_width` | `12` | int |  |
| `frac_bits` | `4` | int | Fractional bits of the coefficient/control fixed-point format. |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | cell |
| `source` | source | target |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 3 bits, reset `0x3`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `local_max` | `1` | Only local maxima become records. |
| `[1]` | `interpolate` | `1` | Parabolic sub-bin interpolation. |
| `[2]` | `clear` | `0` | Clear the frame error. (pulse) |

### `config` (read-only, 28 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[11:0]` | `n_range_bins` | `0` | Rows per CPI. |
| `[23:12]` | `n_doppler_bins` | `0` | Cells per row. |
| `[27:24]` | `frac_bits` | `0` | Sub-bin fractional bits. |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `frame_error` | `0` | Sticky: row framing did not match n_doppler_bins. |

### `count` (read-only, 16 bits)

Records in the last CPI.

### `cpi_count` (read-only, 32 bits)

CPIs processed since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1006 | 427 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_detect.py` (bit-exact/SNR under randomized backpressure).
