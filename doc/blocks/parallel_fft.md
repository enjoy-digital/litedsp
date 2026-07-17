# FFT (parallel, P samples/clk)

`LiteDSPParallelFFT` — `litedsp.analysis.fft_parallel` — category `analysis`

latency: 76 samples · CSR: yes · bypass: no

## Overview

Streaming ``N``-point FFT at P samples/cycle (super-sample-rate wideband path).

The serial radix-2 SDF schedule of :class:`~litedsp.analysis.fft.LiteDSPFFT` regrouped for
two lanes per beat, **bit-identical** to the serial FFT on the flattened lane stream. The
first DIF butterfly rank splits each frame into an ``N/2`` "sum" sub-frame (even bins) and
a twiddled "difference" sub-frame (odd bins):

    ``X[2k]   = FFT_{N/2}( (x[n] + x[n + N/2]) / 2 )``
    ``X[2k+1] = FFT_{N/2}( (x[n] - x[n + N/2]) * W_N^n / 2 )``

which is exactly what serial stage 0 computes (same ``scaled`` 1/2 round+saturate on the
sum, same quantized Q1.(W-1) twiddle product and rescale on the difference); serial stages
1..log2(N)-1 then process the two sub-frames as independent ``N/2``-sample blocks, since
stage ``s`` of an ``N``-point SDF cascade is identical hardware to stage ``s - 1`` of an
``N/2``-point one (same delay ``D = N >> (s+1)``, same twiddle ROM) and SDF butterflies
never mix consecutive blocks. The parallel datapath therefore instantiates two unmodified
serial :class:`~litedsp.analysis.fft.LiteDSPFFT` ``N/2`` cores — one per sub-frame — fed at
one sample/cycle each, with the 2-lane butterfly rank in front. Every rounding happens at
the same position as in the serial machine, so each output frame is bit-exact vs the
serial FFT (``fft_fixed_model``); only the latency differs.

Interface: ``iq_layout(data_width, 2)`` on both sides, lane 0 = first/oldest sample.
A frame is ``N/2`` beats; framing is positional (as in the serial FFT: sink ``first``/
``last`` markers are accepted but not required), and the source carries ``first``/``last``
on beats 0 and ``N/2 - 1`` of each output frame. Output beat ``m`` carries the serial
FFT's (bit-reversed, 1/N-scaled) output stream two beats at a time::

    lane 0 = X[bit_reverse(2m,     log2(N))] = X[r]            r = bit_reverse(m, log2(N/2))
    lane 1 = X[bit_reverse(2m + 1, log2(N))] = X[r + N/2]

i.e. lanes carry consecutive bit-reversed indices: lane 0 sweeps bins [0, N/2) in
``N/2``-point bit-reversed order and lane 1 the mirrored bin ``+ N/2``.

The default ``implementation="split"`` preserves the original P=2 architecture. With
``core_architecture="classic"`` it sustains 2 samples/cycle; ``"folded"`` adds a timing
register to the wide butterfly rank and uses two-cycle serial sub-cores, for a peak width
of two and an average rate of one sample/cycle.

``implementation="native"`` instead advances a single SDF feedback line by P consecutive
samples per clock. It supports P=2 and P=4, sustains P samples/cycle, eliminates the split
implementation's branch FIFOs/serializers/duplicated cores, and remains bit-identical to
the serial FFT on the flattened lane stream. ``feedback_pipeline=True`` registers the
butterfly difference and real twiddle products in ranks with at least two packed feedback
addresses; a same-address forwarding path preserves the recurrence while retaining one beat
per clock. Both implementations use the serial FFT's ``scaling="scaled"`` arithmetic
(1/2 per stage, 1/N overall).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `N` | `64` | int | Transform size (power of two >= 8). |
| `n_samples` | `2` | int | Samples per beat; 2 for ``"split"``, or 2/4 for ``"native"``. Choices: `2`, `4`. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `twiddle_width` | `16` | int | Twiddle-factor width in bits (signed Q1.(W-1)), as in the serial FFT. |
| `core_architecture` | `"classic"` | str | ``"classic"`` for sustained two-sample/cycle throughput, or ``"folded"`` for a registered timing-oriented split path with one-sample/cycle average throughput. Choices: `classic`, `folded`. |
| `implementation` | `"split"` | str | ``"split"`` (compatibility default) or the scalable ``"native"`` vector-SDF engine. Choices: `split`, `native`. |
| `feedback_pipeline` | `False` | bool | Pipeline the native feedback multiplier with same-address forwarding. Adds one clock to each eligible rank without reducing the P-sample-per-clock initiation rate. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `latency` (read-only, 32 bits, reset `0x4c`)

FFT pipeline latency (cycles from frame start to first output).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_fft_parallel.py` (bit-exact/SNR under randomized backpressure).
