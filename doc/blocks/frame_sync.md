# Frame sync (preamble)

`LiteDSPFrameSync` — `litedsp.comm.frame_sync` — category `comm`

latency: 9 samples · CSR: yes · bypass: no

## Overview

Preamble detector + stream aligner: the gateway block for burst receivers.

Correlates the I/Q stream against a known ``sequence`` (complex matched filter, i.e.
:class:`litedsp.comm.correlator.LiteDSPCorrelator` conventions: taps are the conjugated
time-reversed reference at full-scale Q1.(N-1)) and applies a CFAR-style *normalized*
threshold so detection is invariant to input gain::

    detect when |corr|**2 * 2**threshold_frac >= threshold * (N * window_energy)

where ``window_energy`` is the exact moving sum of ``I**2 + Q**2`` over the ``N``
sequence samples ending at the correlated sample, and ``threshold`` is a runtime
unsigned Q2.(threshold_frac) control. By Cauchy-Schwarz ``|corr|**2 <= N*window_energy``,
so ``threshold`` reads as the normalized correlation power: 1.0 is a perfect match,
noise averages ``1/N``; the reset value is 0.5. A zero-energy window (dead line) never
detects. Both compare sides stay in wide exact
fixed-point (no rounding on the detection path): ``|corr|**2`` and ``|x|**2`` grow to
``2*data_width + 1`` bits, the energy window adds ``ceil(log2(N))`` bits, the left side
adds ``threshold_frac`` shift bits and the right side the ``2 + threshold_frac``
threshold plus ``ceil(log2(N))`` scale bits. The only quantization on the path is the
correlator's own round+saturate to ``data_width`` (keep preamble amplitude below
full-scale/N to stay out of correlator saturation).

On a threshold crossing, the local ``|corr|**2`` maximum within the next ``peak_window``
samples is selected as the peak, ``detected`` pulses (counted in a CSR, optional IRQ via
``with_irq=True``), and the output stream — the input delayed by ``self.latency``
samples, payload untouched — is tagged: ``source.first`` on the first sample after the
preamble (peak + 1 + ``offset``), and, when ``frame_len`` is given, ``source.last``
``frame_len`` samples later. New crossings are ignored while an alignment/frame is in
progress (so a preamble-like pattern inside the payload cannot re-trigger mid-frame).

The whole detection pipeline advances only when a sample is consumed (never on input
bubbles), so sample positions and pipeline slots coincide: peak-picking look-ahead and
the ``first``/``last`` alignment are exact under any valid/ready pattern.

``architecture="classic"`` computes input power and ``threshold * (N * window_energy)``
directly at their consumer registers and uses the matched filter's combinational reduction.
``architecture="pipelined"`` registers every matched-filter reduction level, then registers
input power/correlation and splits normalized threshold formation across two stages. It adds
``ceil(log2(N)) + 2`` samples of latency without changing initiation rate, arithmetic, peak
selection, or tags.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `sequence` | `[1, 1, 1, -1, -1, 1, -1]` | list | Reference preamble: complex values, ``(i, q)`` tuples or +/-1 reals (Barker/PN code), components in [-1.0, +1.0]. Length ``N`` sets the correlator tap count (one complex FIR for a real sequence, two for a complex one) and the energy-window length. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `threshold_frac` | `14` | int | Fractional bits of the unsigned Q2.(threshold_frac) detection threshold (1.0 = ``2**threshold_frac`` = perfect correlation power; reset 0.5). |
| `frame_len` | — | none | Frame length in samples; when given, ``source.last`` is asserted ``frame_len`` samples after (and including) the ``first`` sample. ``None`` tags ``first`` only. |
| `peak_window` | `4` | int | Local-maximum search window after a threshold crossing, in samples. Also sets the output look-ahead delay (classic ``latency = correlator latency + peak_window + 2``). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |
| `architecture` | `"classic"` | str | Choices: `classic`, `pipelined`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `threshold` (read-write, 16 bits, reset `0x2000`)

Detection threshold (unsigned Q2.14): detect when |corr|^2 >= threshold * N * window_energy; 1.0 (= 2**14) is a perfect match.

### `offset` (read-write, 8 bits)

Extra samples between peak+1 and the `first` tag.

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the detection counter. (pulse) |

### `count` (read-only, 32 bits)

Detections since reset/clear.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 990 | 2034 | 0 | 23 | 112.4 | 100.0 |
| xilinx | 376 | 572 | 0 | 26 | 125.4 | 100.0 |
| xilinx_au | 371 | 572 | 0 | 26 | 244.7 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_frame_sync.py` (bit-exact/SNR under randomized backpressure).
