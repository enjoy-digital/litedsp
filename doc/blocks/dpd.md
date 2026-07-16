# DPD actuator

`LiteDSPDPD` — `litedsp.level.dpd` — category `level`

latency: 4 samples · CSR: yes · bypass: yes

## Overview

Memory-polynomial-lite (GMP-lite) digital predistortion actuator.

Computes ``y[n] = sum_m x[n-m] * G_m(|x[n-m]|)`` for ``m = 0..n_taps-1``: each branch
multiplies a delayed input sample by a complex gain looked up from that branch's LUT,
indexed by the sample's own magnitude. Tap 0 is the memoryless AM/AM + AM/PM corrector;
the memory taps compensate mild PA memory effects. LUT entries are complex signed
Q2.``coeff_frac`` pairs (|G| < 2), so the actuator can express the gain expansion +
counter-rotation a compressing PA needs.

The magnitude estimate is the two-region alpha-max-beta-min form
``max(hi, hi - hi/8 + lo/2)`` with ``hi = max(|I|, |Q|)``, ``lo = min(|I|, |Q|)``
(shift/add only, ~3% peak error — 4x tighter than the single-region ``hi + lo/4``, which
matters here because the magnitude quantization directly bounds the achievable
linearization). The LUT index is the estimate's top ``log2(lut_depth)`` bits below full
scale (``mag >> (data_width - 1 - log2(lut_depth))``, clamped to the last entry), i.e.
bin ``b`` covers ``|x|`` in ``[b, b + 1) * 2**(data_width - 1) / lut_depth``.

LUTs initialize to the identity (tap 0 = 1.0 + 0j everywhere, memory taps = 0), so the
untrained block is an exact passthrough. They are host-(re)writable through a shared
sequential write bus with a tap-select field (``lut_tap``/``lut_rst``/``lut_data``/
``lut_we`` signals, or the ``lut_tap``/``lut_reset``/``lut`` CSRs): select a tap, strobe
the pointer reset, then write ``lut_depth`` packed ``{Q, I}`` entries. Program while the
stream is quiescent (or bypassed): entries take effect as written.

Fixed point: products are kept full width (data_width + coeff_frac + 3 bits per complex
component covers |G| < 2 plus the cross-term add), the branch sum adds
``ceil(log2(n_taps))`` bits, and a single ``scaled()`` (round-half-up + saturate) by
``coeff_frac`` produces the output — identity LUTs reproduce the input bit-exactly.
Latency is fixed at 4 cycles (magnitude, index, LUT read + complex multiply, sum/scale);
``bypass`` passes the input through delay-matched.

Host adaptation workflow (indirect learning, see :mod:`litedsp.software.dpd`):

1. Capture time-aligned (PA input, PA output) sample records through the existing
   capture path (``LiteDSPCapture``/DMA) — PA input is this block's output.
2. ``DPDAdapter.fit(pa_input, pa_output)`` normalizes the PA output by the estimated
   linear gain, bins it with this block's exact magnitude/indexing arithmetic, solves
   the LUT-basis least-squares postdistorter (``numpy.linalg.lstsq``) and quantizes to
   Q2.``coeff_frac``.
3. ``DPDAdapter.program(DPDDriver(bus, "dpd"))`` writes the LUTs; iterate capture + fit
   once or twice to converge (each iteration refits on the currently-predistorted PA).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_taps` | `3` | int | Memory depth M (number of delayed-sample branches, >= 1). Each tap costs one LUT RAM and a complex multiplier (4 real multipliers). |
| `lut_depth` | `64` | int | Entries per gain LUT (power of two, magnitude bins). 64 matches the resolution of the magnitude estimate; more mainly costs RAM and thins the per-bin fit statistics. |
| `coeff_frac` | `14` | int | Fractional bits of the LUT entries (signed Q2.``coeff_frac`` per component, 1.0 = ``2**coeff_frac``); also the single output rescale shift. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[7:0]` | `taps` | `0` | Memory taps M (delayed-sample branches). |
| `[23:8]` | `depth` | `0` | LUT entries per tap (magnitude bins). |
| `[31:24]` | `frac` | `0` | LUT fractional bits (entries are signed Q2.frac). |

### `lut_tap` (read-write, 2 bits)

Tap (branch) select for LUT writes.

### `lut_reset` (read-write, 1 bit)

Reset the LUT entry write pointer to entry 0 (write to strobe).

### `lut` (read-write, 32 bits)

Write the next LUT entry of the selected tap ({Q, I} packed, each signed Q2.frac; auto-incrementing entry index).

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1559 | 634 | 0 | 12 | 92.9 | 100.0 |
| xilinx | 701 | 180 | 0 | 14 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_dpd.py` (bit-exact/SNR under randomized backpressure).
