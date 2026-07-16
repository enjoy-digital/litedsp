# CFR (peak cancellation)

`LiteDSPCFR` — `litedsp.level.cfr` — category `level`

latency: 1 sample · CSR: yes · bypass: yes

## Overview

Crest-factor reduction by peak cancellation: subtract a scaled low-pass pulse per peak.

Detects local maxima of the alpha-max-beta-min magnitude estimate (same idiom as
:class:`~litedsp.level.agc.LiteDSPAGC`: ``|x| ~ max + min/4``) that exceed the runtime
``threshold`` T, and subtracts a cancellation pulse centered on the peak from the
delay-line-matched stream: ``y[n] = x[n] - g * x_pk * p[n - n_pk]`` with
``g = (|x_pk| - T)/|x_pk|``, so the peak magnitude lands at ~T while the correction
energy stays inside the pulse's low-pass band (bounded ACLR/EVM impact, see
:func:`cfr_pulse`).

The division in ``g`` is avoided with a shift-normalized reciprocal LUT: ``|x_pk|`` is
left-shifted by its leading-zero count ``e`` onto ``[0.5, 1.0) * 2**data_width``
(mantissa ``u in [1, 2)``), a 64-entry midpoint LUT (:func:`cfr_recip_lut`) gives
``r ~ 1/u`` in Q0.15, and ``g = (((|x_pk| - T) << e) * r) >> 15`` (round-half-up,
clamped to Q0.15 max). Max relative error ~0.8% of ``g`` (LUT interval half-width
2**-7), i.e. <1% residual-peak error — well under the alpha-max-beta-min estimate
spread (-11.6%..+3.1% vs the true magnitude), which sets the residual-peak accuracy.

Single-engine simplification: one pulse generator; while it plays a pulse
(``pulse_span + 1`` samples), further above-threshold local maxima pass uncorrected and
are counted in ``missed_count`` (``peak_count`` counts fired/corrected peaks). Cycle
latency is 1; the datapath additionally delays the signal by ``self.delay =
pulse_span/2 + 2`` samples (delay line + 1-sample local-max lookahead) so the pulse
center aligns with the peak.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `pulse_span` | `16` | int | Cancellation pulse span in samples (even, >= 4; the pulse has ``pulse_span + 1`` taps). Longer = more spectrally contained corrections, but longer engine busy time (more missed peaks at high peak density) and a deeper delay line. |
| `threshold` | — | none | Reset value of the runtime peak threshold, compared against the alpha-max-beta-min magnitude estimate (~|x|, full-scale units). Defaults to ``2**data_width - 1`` (above any reachable estimate, i.e. correction disabled until programmed). |
| `cutoff` | `0.25` | float | Pulse low-pass cutoff in normalized frequency (0..0.5]; set to the signal's one-sided bandwidth so corrections stay in-band (see :func:`cfr_pulse`). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

### `threshold` (read-write, 16 bits, reset `0xffff`)

Peak threshold, in alpha-max-beta-min magnitude units (~|x|).

### `peaks` (read-only, 32 bits)

Corrected peaks (cancellation pulses fired). Wraps.

### `missed` (read-only, 32 bits)

Uncorrected peaks (detected while the pulse engine was busy). Wraps.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 757 | 459 | 0 | 5 | 55.5 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_cfr.py` (bit-exact/SNR under randomized backpressure).
