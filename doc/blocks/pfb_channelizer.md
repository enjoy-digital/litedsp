# PFB channelizer (scalable)

`LiteDSPPFBChannelizer` — `litedsp.mixing.pfb_channelizer` — category `mixing`

latency: 60 samples · CSR: yes · bypass: no

## Overview

Uniform filter bank (polyphase FIR + scalable direct/FFT transform).

A commutator distributes consecutive input samples over ``M = n_channels`` polyphase
branches; every ``M/oversampling`` input samples, each branch computes a
``taps_per_channel``-tap dot-
product over its sample history (prototype phase ``p``: taps ``coefficients[p::M]``,
newest frame sample on branch 0) and the M branch results feed an M-point DFT with
kernel ``exp(+2j*pi*k*p/M)``. ``oversampling=1`` preserves the aggregate rate: M channel
samples out per M inputs. ``oversampling=2`` uses overlapping histories and emits M
samples per M/2 new inputs; odd channels receive the alternating half-frame phase
correction required to keep a channel-center tone at DC. Each output set is a framed
burst (``first`` on channel 0, ``last`` on channel M-1).

Channel convention: channel ``k`` is the band centered at ``+k/M`` of the input sample
rate (``k > M/2`` wraps to the negative frequencies, center ``(k - M)/M``), brought to
baseband and decimated by M — an input tone at exactly ``k/M`` lands as DC in channel
``k``; a tone at ``k/M + d`` (``|d|`` inside the prototype passband) lands in channel
``k`` as a tone at ``d*M`` of the channel output rate. Adjacent-channel isolation is
the prototype's stopband attenuation at the neighboring channel offsets ``l/M``.

Fixed-point: coefficients and DFT twiddles are signed Q1.(W-1). Bit growth is carried
in full: branch accumulators are ``2*W + clog2(T) + 1`` bits (product + accumulation),
DFT accumulators add ``W + clog2(M) + 1`` bits (twiddle product + M-term sum); a single
:func:`litedsp.common.scaled` (round half-up + saturate) by ``2*(W - 1)`` bits (the
coefficient + twiddle fractional bits) produces the output — no intermediate rounding.

Throughput: one shared MAC, ``H + M*(T + 1) + M*(M + 1)`` cycles per frame, where
``H = M/oversampling``
(load + branch FIRs + DFT/emit), so ``fs_in <= f_clk * M / cycles_per_frame`` (roughly
``f_clk / (T + M + 3)``); the input is stalled (backpressured) while a frame computes.
``architecture="folded"`` separates every multiply from its recursive accumulation,
increasing this to ``M + M*(2*T + 1) + M*(2*M + 1)`` cycles while preserving the exact
full-precision sums. ``"classic"`` remains the default.

``architecture="auto"`` is the unified scalable option: it selects the direct transform
for ``M <= 8`` and the time-multiplexed radix-2 DIF transform for ``M >= 16``.
``architecture="fft"`` selects that FFT transform explicitly.
It uses the timing-oriented two-cycle polyphase MAC and computes one butterfly in four
clocks (registered read/difference, registered multiply, then two single-port
feedback-memory writes), reducing the DFT work from O(M^2) to O(M log2(M)) while retaining
full branch precision and natural channel order. Twiddle products round back to the branch
accumulator's fractional scale after each FFT rank; this arithmetic has its own bit-exact
golden model.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_channels` | `4` | int | Number of uniformly-spaced channels M (power of two; 2..8 for direct/folded DFT, M >= 16 for the FFT stage). Channel k is centered at ``k/M`` of the input rate. |
| `taps_per_channel` | `8` | int | Prototype taps per polyphase branch T (prototype length = ``n_channels * taps_per_channel``). Sets the channel shape/stopband and the MAC length. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coefficients` | — | none | Prototype low-pass taps, signed Q1.(W-1) integers, length ``n_channels * taps_per_channel`` (default: ``firwin_lowpass(M*T, 0.4/M)``, unity DC gain, so a full-scale tone at a channel center emerges at full scale in that channel). |
| `architecture` | `"auto"` | str | ``"auto"`` to select classic for M <= 8 and FFT for M >= 16, ``"classic"`` for one MAC term per clock, ``"folded"`` for separate multiply and accumulate clocks in both direct sections, or ``"fft"`` for the scalable DFT stage. Choices: `auto`, `classic`, `folded`, `fft`. |
| `oversampling` | `1` | int | Aggregate output/input rate: 1 for critically sampled (M outputs per M inputs), or 2 for overlapping frames (M outputs per M/2 inputs) with odd-bin phase correction. |

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
| `[15:0]` | `channels` | `0` | Number of channels M. |
| `[31:16]` | `taps` | `0` | Prototype taps per polyphase branch. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1040 | 212 | 0 | 11 | 56.5 | — |
| xilinx | 490 | 216 | 0 | 10 | — | — |
| xilinx_au | 449 | 217 | 0 | 10 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_pfb_channelizer.py` (bit-exact/SNR under randomized backpressure).
