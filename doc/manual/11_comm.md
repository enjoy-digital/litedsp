# Communications blocks {#comm}

This chapter describes the comm family: the 51 blocks that modulate and demodulate, synchronize
a receiver, code and frame bit streams, correct errors and handle OFDM symbols. Read it to choose
the blocks of a modem and to set their parameters. The concepts are explained in [Digital
communications](#comm-primer); this chapter gives the LiteDSP implementation of each one.

## At a glance {#comm-glance}

| Item | Value |
|------------------------|-----------------------------------------------------------------------|
| Package | `litedsp/comm/` (33 files), registry family `comm` |
| Blocks | 51 registry entries in eight groups, listed in [Block list](#comm-list) |
| Sample streams | `iq_layout` (I/Q), `real_layout`, `iq_symbol_layout` (I/Q and a symbol index) |
| Bit and byte streams | `data` of 1 bit (bit streams), 8 bits (Reed-Solomon, interleavers) |
| Soft bits | Packed signed LLRs on an `llrs` field, positive means bit 0 |
| Block codes | Block boundaries counted from reset, outputs framed with `first` and `last` |
| Timing options | `architecture="classic"` or `"pipelined"` on the recurrence-limited blocks |
| Golden models | `test/models.py` for most blocks, bit identical to the gateware |
| Registers | [Communications registers](#reg-comm); datasheets in the [block catalogue][w5cat] |
| Status | See [status](#intro-status) |

[w5cat]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md

The figure below shows how the blocks combine into a burst receiver. Acquisition estimates the
frequency offset and finds the preamble; tracking follows the carrier and the symbol timing and
makes the decisions. The chain is an illustration: each block is a separate stream block, and a
design picks the ones its signal needs.

![A burst receiver built from comm blocks. Follow the samples from the CFO estimator, which
measures the offset and programs the derotator, to the frame synchronizer, which tags the frame,
then through the tracking loops to the decisions. The cyan blocks are comm blocks; the derotator
and the matched filter come from the correction and filter families. The frame tags reach the
carrier loop; the timing recovery, which changes the rate, does not carry them.](com_rx.svg)

## Conventions {#comm-conventions}

The comm blocks follow the block contract of [Block contract](#architecture): LiteX streams with
`valid`/`ready` flow control, a `latency` attribute in samples, `with_csr` to add the registers
and a per-block reset. A few conventions are specific to the family.

**Bit streams.** Bit-level blocks (scrambler, CRC, line codes, HDLC, Hamming, BCH, LDPC encoder)
carry one bit per beat on a `data` field of width 1.

The convolutional encoder emits `n` coded bits per beat, bit `j` for generator `j`; the Reed-Solomon
codec and the interleavers carry one byte per beat. The HDLC blocks take payloads LSB first, the
order of the LiteX stream converters.

**Soft bits.** Every soft block uses one LLR convention: a signed integer of `llr_bits` bits,
positive when bit 0 is more likely, and 0 for an erasure.

Several LLRs in one beat are packed LSB first on an `llrs` field, slot `j` at bits `[j*llr_bits +:
llr_bits]`. The soft demapper, the depuncturer, the Viterbi decoder and the LDPC decoders all agree
on it, so they connect without glue.

**Block codes.** The Reed-Solomon, BCH, Hamming, LDPC codecs and the block interleavers count
block boundaries from reset and ignore the `first` and `last` of their input. Their outputs are
framed: `first` on the first beat of each block, `last` on the last one. Align the stream before
these blocks, with a frame synchronizer or a reset, and keep whole blocks flowing.

**Variable latency.** A block that buffers a block or changes the rate has `latency = None`. The
decoders publish their worst-case schedule as an attribute instead, `cycles_per_block` (or
`cycles_per_output` for the Viterbi decoder), in clock cycles and without handshake stalls. The
input stalls while a block decodes.

**Status counters.** The decoders report the same way: `corrected` for the last block, a
cumulative `corrected_total`, a sticky `uncorrectable` flag with its `uncorrectable_count`, and
`clear` to reset the sticky flag and the counters. The LDPC decoders report `iterations`,
`parity_ok` and `failures` instead.

**Timing options.** Blocks whose feedback loop limits the clock rate offer faster schedules as
options, summarized in [Timing options](#comm-timing).

## Modulators and demodulators {#comm-modem}

The modulators turn a real message or a symbol stream into complex baseband I/Q, ready for a DUC
or a DAC interface. The demodulators turn I/Q back into a real message. [Analog
modulations](#cpri-analog) explains each modulation.

| Block | In | Out |
|-------------------|-----------|-----------|
| AM modulator | real | I/Q |
| FM modulator | real | I/Q |
| PM modulator | real | I/Q |
| SSB modulator | real | I/Q |
| FSK modulator | symbols | I/Q |
| FM demodulator | I/Q | real |
| AM demodulator | I/Q | real |
| Phase detector | I/Q | angle |

The latencies are in the [Block list](#comm-list).

The FM and PM modulators share one angle engine. The message is multiplied by a `deviation` word and
added to a carrier phase increment `phase_inc`.

FM accumulates the sum as the phase of the next sample; PM adds the message to a free-running
carrier phase. A quarter-wave cosine and sine ROM gives I and Q, and the phase only advances on
accepted samples.

The AM modulator computes the envelope `2**(data_width-2) * (1 + m * x)`: a half-scale carrier,
so an index `m` of 1.0 or less never overflows. With `carrier="baseband"`, I carries the envelope
and Q is zero (latency 2); with `carrier="nco"`, the envelope multiplies an internal carrier
(latency 4).

The SSB modulator uses the phasing method. A Hilbert filter of `n_taps` taps (31 by default)
makes the quadrature path, and the `sideband` control selects the upper or the lower sideband at
run time. Its `latency` is the pipeline of the Hilbert filter, 3 samples; the filter adds
`(n_taps - 1)/2` samples of group delay to the signal, 15 with 31 taps.

The FSK modulator maps each symbol of `bits_per_symbol` bits to a frequency level, holds it for
`sps` samples and feeds the FM engine.

With `bt` set, a Gaussian FIR filter smooths the levels: GFSK, or GMSK with a modulation index of
0.5. `fir_architecture` picks a parallel or a time-shared multiplier FIR. The helper
`fsk_deviation()` computes the deviation word for a given modulation index.

The FM demodulator multiplies each sample by the conjugate of the previous one and takes the
angle with a CORDIC in vectoring mode ([CORDIC](#pri-cordic)). Its output is the phase step per
sample, full circle `2**angle_width`, and its latency is the CORDIC pipeline. The phase detector
is the same CORDIC on the sample itself.

The AM demodulator takes the magnitude of the sample and removes the carrier DC with a
multiplier-free first-order high-pass filter, whose pole is `1 - 2**-pole_shift`.

The helper `fsk_deviation()` and the other host helpers are in `litedsp/comm/design.py`.

## Mapping and decisions {#comm-mapping}

The mapping blocks convert between symbol indices and constellation points, and between points
and hard or soft bits. All of them use the square QAM convention of [Constellations and Gray
coding](#cpri-constellations): `L = 2**bits_per_axis` levels per axis at
`(2k - (L - 1)) * spacing`.

| Block | In | Out |
|-----------------------|-------------|-----------------|
| Symbol mapper | `symbol` | I/Q |
| Slicer | I/Q | I/Q, `symbol` |
| Soft demapper | I/Q | `llrs` |
| Gray mapper, demapper | `data` | `data` |
| Differential encoder, decoder | `data` | `data` |

The symbol index is `[q_bits | i_bits]`, `bits_per_axis` bits for each axis: 1 for QPSK, 2 for
16-QAM. The mapper and the slicer are exact inverses on that index; the slicer also outputs the
decided point, so it can feed a decision-directed loop. Both take `spacing`, half the distance
between adjacent levels, in LSBs (8192 by default).

The soft demapper computes the max-log LLR of every bit of a Gray-coded square QAM point
([Hard and soft decisions](#cpri-decisions)). Each axis carries `bits_per_axis` bits; the LLR of
the most significant bit is the negated axis value, and each lower bit folds the previous one
around `2**(j+1) * spacing`. Only additions, absolute values and comparisons are needed.

The raw LLRs are in axis LSBs. The `llr_scale` register, unsigned Q1.15 with a reset value of 1.0,
scales them before a symmetric saturation to `2**(llr_bits-1) - 1`. Program it from the noise
variance measured by the host. The output beat packs `2*bits_per_axis` LLRs, I-axis bits first,
in the same slot order as the slicer's symbol bits.

The Gray mapper and demapper convert `n_lanes` words of `width` bits per beat between binary and
Gray code. The differential encoder outputs `(in + out[n-1]) mod M` and the decoder
`(in - in[n-1]) mod M`, with `modulus` M of 2 for DBPSK and 4 for DQPSK.

## Synchronization {#comm-sync}

Five blocks synchronize a receiver: a correlator and a frame synchronizer find the preamble, a
CFO estimator measures the frequency offset, a carrier loop locks the phase, and a timing recovery
block finds the symbol instants. [Carrier recovery](#cpri-carrier), [Symbol timing
recovery](#cpri-timing) and [Frame synchronization](#cpri-frame-sync) explain the methods.

### Correlator {#comm-correlator}

The correlator is a complex FIR whose taps are the time-reversed reference `sequence`, scaled to
full scale (`LiteDSPCorrelator`). Its output peaks when the input lines up with the sequence. The
sequence is real: a ±1 Barker or PN code gives ±full-scale taps. Follow it with a magnitude and a
threshold, or use the frame synchronizer, which does both.

### Frame synchronizer {#comm-frame-sync}

The frame synchronizer is the entry block of a burst receiver (`LiteDSPFrameSync`).

It correlates the I/Q stream with a complex or real `sequence`, detects the preamble with a
gain-independent threshold, and tags the stream: `first` on the first sample after the preamble and,
when `frame_len` is given, `last` at the end of the frame. The samples pass through unchanged,
delayed by the block latency.

The detection compares, without any rounding:

```text
|corr|**2 * 2**threshold_frac  >=  threshold * (N * window_energy)
```

`window_energy` is the exact sum of `I**2 + Q**2` over the `N` samples that the correlation covers.

By the Cauchy-Schwarz inequality, the left side never exceeds the right one with a threshold of 1.0,
so `threshold` reads as the normalized correlation power: 1.0 for a perfect match, about `1/N` for
noise. It is an unsigned Q2.`threshold_frac` register, 0.5 at reset. A window of zero energy never
detects.

After a threshold crossing, the block searches the largest `|corr|**2` within the next `peak_window`
samples (4 by default) and takes it as the peak. It pulses `detected`, increments the `count`
register, and raises an interrupt with `with_irq=True`.

The `offset` register adds samples between the peak and the `first` tag. A new crossing is ignored
until the current frame ends, so a preamble-like pattern inside the payload cannot restart it.

The whole detection pipeline advances only on accepted samples. Peak positions and tags are
therefore exact under any pattern of input bubbles and output backpressure. The classic latency is
the correlator latency plus `peak_window + 2`: 9 samples for the 7-chip Barker code of the
registry.

The classic detector has three long paths: the matched-filter sum, the energy update, and the
`threshold * (N * energy)` product. `architecture="pipelined"` registers each level of the
matched-filter reduction, registers the power and the correlation before the energy update, and
splits the threshold product over two stages.

It adds `ceil(log2(N)) + 2` samples of latency, 5 for Barker-7, and keeps one sample per clock; the
arithmetic, the peak and the tags do not change.

On the Xilinx devices, the pipelined option uses three more DSP blocks per I/Q matched filter,
the cost of keeping Vivado from merging the run-time coefficient reduction into a DSP cascade.
Classic is the default; [Communications results](#perf-comm) gives both.

### CFO estimator {#comm-cfo}

The CFO estimator measures a carrier frequency offset from a signal that repeats every `delay`
samples (`LiteDSPCFOEstimator`). It sums `x[n] * conj(x[n - delay])` over `2**span_log2` samples
with exact arithmetic, takes the angle of the sum with a CORDIC, latches it and pulses
`estimate_ready`.

Then the next span starts. The stream passes through unchanged with a latency of 0: the estimator is
a tap in front of a derotator.

The capture range is `|f| < 1/(2*delay)` cycles per sample. `delay` is a power of two, so the
correction for the derotator NCO is an exact shift of the angle: the block outputs it as
`phase_inc_correction`, ready to write to the `phase_inc` of a `LiteDSPDerotator`
([Generation and mixing](#generation-mixing)). Its scaling assumes the NCO's `phase_bits`, also
a parameter of the estimator.

Longer spans average more noise but update less often; the first span after reset includes
`delay` zero products while the delay line fills. The `angle`, `phase_inc` and `count` registers
expose the last estimate.

### Carrier loop {#comm-carrier}

The carrier loop derotates each sample by the phase of an internal NCO and drives the NCO with a
PI loop from a phase detector (`LiteDSPCarrierLoop`). The derotated signal is the output. The
`detector` parameter selects the error, as in [Carrier recovery](#cpri-carrier):

| Detector | Signal | Error |
|--------------|---------------------------------|-------------------------------------|
| `"pll"` | Residual carrier | Q of the derotated sample |
| `"bpsk"` | BPSK (Costas) | `sign(I)*Q` |
| `"qpsk"` | QPSK, decision directed | `sign(I)*Q - sign(Q)*I` |

Three alias classes fix the detector: `LiteDSPPLL`, `LiteDSPCostas` and `LiteDSPQPSKCostas`, in
that order.

The detectors use signs, not multipliers. The proportional and integral gains are powers of two,
`2**-kp_shift` and `2**-ki_shift` (6 and 14 by default); a larger shift gives a slower, quieter
loop. The NCO reads cosine and sine tables of `lut_depth` entries, addressed by the top phase
bits. The `frequency` register returns the PI integrator: the recovered carrier frequency.

In the classic architecture, the error of a sample is applied to the next accepted sample. That
one-sample loop holds the NCO table read, four products, the detector and the PI update in one
cycle, which limits the clock rate of the complete QPSK receiver core.

`architecture="pipelined"` makes the loop explicitly four samples long. It registers the NCO
operands, the mixer products and the rounded derotation before the detector; a four-entry queue
applies the error of sample `n` to sample `n + 4`.

The queue counts accepted samples, so input bubbles and output backpressure never change the loop
delay. The output latency rises from 1 to 3 samples, and the throughput stays one sample per clock.

A longer loop delay changes acquisition and jitter, which is why it is an option.

On the QPSK acquisition stimulus of the regression tests, the classic and the pipelined loops lock
in 609 and 608 samples and settle at the same 1.769 mrad RMS phase error. That validates the gains
of the test; other channels may behave differently.

### Timing recovery {#comm-timing-recovery}

The timing recovery block resamples a stream at `sps` samples per symbol (2 by default) to one
sample per symbol, at the symbol centres (`LiteDSPTimingRecovery`). It keeps `omega`, the samples
per symbol, and `mu`, the fractional phase, as in [Symbol timing recovery](#cpri-timing).

Each symbol, a cubic Farrow interpolator computes the sample at `mu` and the detector forms the
timing error. The loop then updates `omega` by `gain_omega` times the error, clamped to `sps` ±5 %,
and advances `mu` by `omega` plus `gain_mu` times the error.

The integer part of `mu` is the number of input samples to consume. `gain_mu` is 0.1 by default and
`gain_omega` defaults to `gain_mu**2/4`, the critically damped choice.

The `ted` parameter picks the detector: `"mm"` for Mueller and Muller, decision directed and
multiplier-free, or `"gardner"`, which interpolates a second point at mid-symbol and needs
`sps=2`. The `omega` register returns the current samples-per-symbol estimate. The output rate
depends on the signal, so the latency is `None`.

The interpolator is registered and settles over a few cycles after the last consumed sample, so only
one multiplication level sits between registers.

The block waits `settle_cycles` cycles, 5 in the classic architecture, before it emits a symbol; it
therefore takes `sps + 5` cycles per symbol. `architecture="pipelined"` also registers the Farrow
sum and the scaled loop corrections: 7 settling cycles, the same accepted-sample trajectory, shorter
paths.

### The generated QPSK receiver {#comm-qpsk-core}

The example `examples/qpsk_receiver_core.yml` chains the carrier loop with the QPSK detector, the
timing recovery with the M&M detector at 2 samples per symbol, and a QPSK slicer. Both loops use
the pipelined architecture. The generator turns it into a standalone AXI-Stream and AXI-Lite core
([Flow, generator, GUI and host software](#tooling)):

```sh
litedsp_gen examples/qpsk_receiver_core.yml --output-dir build/qpsk_receiver_core
```

The implementation runs keep this core as a timing sentinel with a 100 MHz target on the three
reference devices; its results are under the generated IP cores of
[Performance and resources](#performance). The registered NCO address of the pipelined loop lets
both tables map to block RAM.

The aliases `LiteDSPPLL`, `LiteDSPCostas` and `LiteDSPQPSKCostas` are in `pll.py`, next to
`LiteDSPCarrierLoop`.

## Line codes, scrambling and framing {#comm-bits}

These blocks work on bit streams, one bit per beat; [Line codes, scrambling and
framing](#cpri-bit-coding) explains them.

| Block | Bits in to bits out |
|---------------------|----------------------------------|
| Line encoder, decoder | 1 to 1, or 1 to 2 chips and back |
| Scrambler, descrambler | 1 to 1 |
| CRC | 1 to 1 |
| HDLC framer | Adds flags, stuffing and FCS |
| HDLC deframer | Removes them |

The line encoder and decoder support four `code` values. `nrzi_s` toggles the level on a 0, as HDLC
and AIS do, and `nrzi_m` toggles on a 1.

`manchester` sends a bit `b` as the chips `b` then `~b`; `diff_manchester` always has a mid-bit
transition and adds one at the bit start for a 0. The registry also lists the Manchester
configurations as separate entries.

The Manchester decoder consumes chip pairs. A pair without a mid-bit transition is a
`violation`, counted and flagged; `phase_rst` realigns the pair phase. `invert` flips the line
polarity on both sides.

The scrambler is multiplicative and self-synchronizing; its `polynomial` lists the feedback taps,
`(18, 23)` by default for `1 + x^18 + x^23`. The descrambler takes the same taps.

The CRC block passes the bits through and updates its `crc` register, MSB first; `clear` reloads
`init`. The defaults are CRC-16-CCITT: `poly=0x1021`, `init=0xFFFF`.

The HDLC framer turns a payload, LSB first and ended by `last`, into a complete frame: `preamble`
opening flags, the bit-stuffed payload, the X.25 FCS (16 bits, inverted, LSB first) and a closing
flag. It marks `first` on the first flag bit and `last` on the last bit of the closing flag.

The HDLC deframer finds the flags, removes the stuffed zeros and checks the FCS. It holds the
received bits in a 24-bit register and releases a bit once 24 newer ones have arrived.

The FCS and the start of the closing flag therefore never leave the block, and the last payload bit
carries `last` together with the `fcs_ok` verdict. Frames without payload are ignored; an abort,
seven ones, drops the frame. The registers count frames, FCS errors and aborts.

The host helpers `hdlc_fcs()`, `hdlc_stuff()` and `hdlc_frame_bits()` are in
`litedsp/comm/design.py`.

## Forward error correction {#comm-fec}

The FEC blocks cover the codes of [Forward error correction](#cpri-fec). They are bit-exact
against their golden models, including the corner cases of each decoder: ties in the Viterbi
decoder, erasures, and uncorrectable blocks.

| Code | Transmit block | Receive block | Receive input |
|----------------------------|-----------------------|----------------------------|---------------|
| Convolutional | Encoder | Viterbi decoder | Bits or LLRs |
| Puncturing | Puncturer | Depuncturer | LLRs |
| Reed-Solomon | Encoder | Decoder | Bytes |
| Reed-Solomon, CCSDS | Encoder | Decoder | Bytes |
| BCH | Encoder | Decoder | Bits |
| Hamming | Encoder | Decoder | Bits |
| LDPC, 802.11n | Encoder | Serial or lift-parallel decoder | LLRs |
| Block interleaving | Interleaver | Deinterleaver | Symbols |
| Convolutional interleaving | Interleaver | Deinterleaver | Symbols |

### Convolutional encoder {#comm-conv}

The convolutional encoder takes one bit per beat and emits `len(polys)` coded bits, bit `j` the
parity of generator `polys[j]` (`LiteDSPConvEncoder`). The default is the K=7, rate-1/2 code with
generators `0o171` and `0o133`; `constraint` and `polys` select another code.

### Viterbi decoder {#comm-viterbi}

The Viterbi decoder decodes the output of the encoder with the same `constraint` and `polys`
(`LiteDSPViterbiDecoder`). With `llr_bits=None`, the sink carries the `n` coded bits of one symbol
and the branch metric is the Hamming distance.

With `llr_bits` set, the sink carries `n` packed LLRs and the branch metric is the max-log metric.
An erased LLR of 0 costs nothing to either hypothesis, which is how punctured bits are decoded.

When the LLR magnitudes are constant, for example saturated, the soft metric is a scaled Hamming
distance and the decisions equal those of the hard decoder.

The default `traceback` depth is `8*K` symbols, 56 for K=7. Decoded bit k leaves `traceback`
samples after coded symbol k, which is the `latency` of the register exchange decoder. The first
`traceback - 1` symbols only fill the registers, and the last `traceback - 1` bits of a burst leave
only when more symbols follow (flush with `traceback - 1` tail symbols).
`metric_width` sizes the path metric registers; the default is checked against the largest metric
spread of the code.

The decoder has two survivor architectures. The default, *register exchange*, updates all 64 path
metrics and 64 survivor registers of `traceback` bits every symbol, and decodes one bit per input
symbol.

Its loop holds the branch metric addition, the ACS, a six-level minimum over the states, and the
subtraction of that minimum from every metric, which limits the clock rate; the survivors cost
about 3.9k flip-flops.

`decision_memory=True` selects the *decision memory* architecture of the figure below. The ACS units
write one row of decisions per symbol into a RAM. Two registered three-level reductions find the
best state outside the ACS loop, and a folded traceback reads the RAM back from it.

The metrics are normalized every `normalize_interval` accepted symbols (16 by default), in a
separate clock, with wider metric registers absorbing the growth in between.

![Viterbi decoder with decision memory. Follow the loop of the ACS units through the path metrics:
it is the only per-symbol feedback. The decisions leave the loop into the RAM, and the traceback
starts from the best state to produce one decoded bit.](com_viterbi.svg)

The traceback takes `2*(traceback - 1)` clocks, 110 at K=7, and the nominal `cycles_per_output`
is `2*traceback + 2`, 114. Each output costs one traceback, plus one normalization clock every
`normalize_interval` symbols. The sink stalls during the best-state search, the normalization and
the traceback, so this architecture trades coded throughput for area and clock rate.

`acs_parallelism=32` folds the 64 ACS units of K=7 into 32 used in two phases, with
`decision_memory=True` only. The old metrics stay unchanged while both halves are computed, and a
commit clock writes the 64 new metrics and the decision row at once; ties and the traceback path
are unchanged. It adds two clocks per output (`cycles_per_output` 116).

Folding the ACS units saves LUTs but about doubles the flip-flops, because of the holding row; it
is a trade, not a general area reduction ([Communications results](#perf-comm)).

Register exchange is the default, and the 64-ACS decision memory decoder is the recommended
choice for clock rate and flip-flops. A decoder that decodes one symbol per clock at a high clock
rate would need several independent metric contexts, for interleaved codewords; LiteDSP does not
provide one.

The snippet below connects a soft demapper to a soft Viterbi decoder, the inner decoder of a
QPSK link with the coded bit `g0` on I and `g1` on Q. The two LLRs of the demapper beat fill the
two slots of the decoder symbol, so the streams connect directly.

```python
from migen import *

from litex.gen import *

from litedsp.comm.soft_demap import LiteDSPSoftDemapper
from litedsp.comm.viterbi    import LiteDSPViterbiDecoder

class SoftQPSKDecoder(LiteXModule):
    def __init__(self):
        # QPSK point to two 4-bit LLRs (I axis for g0, Q axis for g1).
        self.demap = LiteDSPSoftDemapper(bits_per_axis=1, spacing=8000, llr_bits=4)
        # Soft K=7 Viterbi decoder with decision RAM and folded traceback.
        self.viterbi = LiteDSPViterbiDecoder(llr_bits=4, decision_memory=True)
        self.sink   = self.demap.sink
        self.source = self.viterbi.source
        self.comb += self.demap.source.connect(self.viterbi.sink)
```

### Puncturing {#comm-puncture}

The puncturer takes one coded symbol of `n` bits per beat and emits the bits that the puncturing
matrix keeps, one per beat, row 0 first (`LiteDSPPuncturer`).

The depuncturer takes one LLR per beat in the same order and rebuilds full `n`-slot symbols, with an
LLR of 0 at each dropped position, for the soft Viterbi decoder (`LiteDSPDepuncturer`). Both have a
variable rate, and `phase_rst` realigns the pattern on a block boundary.

The `pattern` parameter is the matrix: one row per coded stream, one column per period position,
1 to keep a bit. `puncture.py` provides the DVB-S matrices of ETSI EN 300 421:

| Constant | Rate | Kept bits per period |
|----------------|------|--------------------------|
| `PUNCTURE_1_2` | 1/2 | X1 Y1 |
| `PUNCTURE_2_3` | 2/3 | X1 Y1 Y2 |
| `PUNCTURE_3_4` | 3/4 | X1 Y1 Y2 X3 |
| `PUNCTURE_5_6` | 5/6 | X1 Y1 Y2 X3 Y4 X5 |
| `PUNCTURE_7_8` | 7/8 | X1 Y1 Y2 Y3 Y4 X5 Y6 X7 |

X is the stream of generator `0o171` and Y the stream of `0o133`. Other standards use
permutations of the same rates, which a custom `pattern` expresses directly. The registry entries
use the rate 3/4.

### Interleavers {#comm-interleavers}

The block interleaver writes `rows` by `cols` symbols row by row and reads them column by column
(`LiteDSPBlockInterleaver`); the block deinterleaver applies the inverse permutation. The defaults,
`rows=5`, `cols=255` and `width=8`, are the CCSDS interleaving depth of 5 on RS(255,223)
codewords.

Both blocks use a ping-pong RAM of two blocks: one bank fills while the other drains, so
consecutive blocks stream at one symbol per clock. A block must be complete before its first
symbol leaves, so the latency is variable. The `filled` signal gives the number of complete banks
not yet read.

The convolutional (Forney) interleaver delays branch `j` of `branches` by `j * depth` symbols
(`LiteDSPConvolutionalInterleaver`), and the deinterleaver by `(branches - 1 - j) * depth`. The
defaults, 12 branches and a depth of 17 bytes, are those of DVB.

All the delay lines share one RAM, the latency is 2 samples, and the blocks have a `bypass` and a
`phase_rst` that restarts the commutator. The RAM starts at zero, so the first outputs are zeros
until the lines fill.

### Reed-Solomon codec {#comm-rs}

The Reed-Solomon codec works on RS(255, `k`) over GF(2^8), with `n - k` even and `t = (n - k)/2`
from 1 to 16; the default is RS(255,223), `t = 16`. The generic classes use the field polynomial
`0x11D`, a first consecutive root `fcr` of 0 and a root step `prim` of 1; all three are
parameters.

The encoder (`LiteDSPRSEncoder`) passes the `k` message bytes through while a `2t`-stage LFSR
divides by the generator polynomial, then sends the `2t` parity bytes, highest degree first.

The decoder (`LiteDSPRSDecoder`) follows the steps of [Block codes](#cpri-block-codes), as the
figure below shows. It writes the `n` received bytes into a block RAM while `2t` syndrome
accumulators run.

A serial Berlekamp-Massey machine finds the error locator, a serial loop computes the error
evaluator Omega, and a Chien scan over the `n` positions computes the Forney magnitudes on the fly.
The located errors are corrected in the RAM, then the `k` message bytes drain.

![Reed-Solomon decoder. Follow the received block into the RAM and the syndromes, then along the
top row to the Chien and Forney step, which corrects the stored bytes before they drain as the
message.](com_rs.svg)

A block with more than `t` errors, detected by the locator degree or by the number of roots, is
passed through uncorrected and counted as uncorrectable. The worst-case schedule is:

```text
cycles_per_block = n + 2 + 2t(2t + 3) + t(t + 1)/2 + 1 + n + 2t + 2k + 2
```

That is 2249 clocks for RS(255,223), about 8.8 clocks per byte, plus handshake stalls; the sink
stalls while a block decodes and drains.

The classic schedule chains GF multiplications, selections and reductions within the
Berlekamp-Massey, Omega and Chien clocks. `architecture="pipelined"` registers the multiplier
operands, drains the serial recurrences explicitly, splits the Chien reductions and registers the
inverse operands and the final magnitude.

The algorithm, the corrections, the framing and the counters do not change; the schedule grows by
`3n + 7t` clocks, to 3126 for RS(255,223).

Classic is the default of `LiteDSPRSDecoder`; [Communications results](#perf-comm) gives both
architectures.

The CCSDS classes select the RS(255,223) profile of CCSDS 131.0-B-5 (`LiteDSPCCSDSRSEncoder` and
`LiteDSPCCSDSRSDecoder`): field polynomial `0x187`, first root 112, root step 11. They convert
between the Berlekamp dual basis of the standard and the conventional basis of the generic codec at
their stream boundaries, with combinational maps that add no cycle.

The CCSDS decoder, unlike the generic one, defaults to the pipelined schedule. The encoder parity is
checked against an independent known-answer vector, so the byte stream interoperates with other
CCSDS implementations.

### BCH and Hamming codecs {#comm-bch-hamming}

The BCH codec works on narrow-sense binary BCH(n, k) codes over GF(2^m) that correct `t` errors,
bit-serial (`LiteDSPBCHEncoder`, `LiteDSPBCHDecoder`). The defaults, `m=4` and `t=2`, give
BCH(15,7); the host helper `bch_generator()` computes the generator polynomial.

The BCH decoder computes the `2t` syndromes by Horner's rule while it stores the codeword, runs a
serial binary Berlekamp-Massey with a small inverse ROM, scans the `n` positions with a Chien search
and flips the roots, then streams the `k` message bits.

Its schedule is `n + 2 + 2t(t + 2) + n + k + 2` clocks. A locator of degree above `t`, or with fewer
roots than its degree, flags the block as uncorrectable.

The Hamming codec works on the (2^m - 1, 2^m - 1 - m) codes, `m=3` by default for Hamming(7,4)
(`LiteDSPHammingEncoder`, `LiteDSPHammingDecoder`). The codeword is the message followed by the
`m` parity bits. With `secded=True`, an overall parity bit follows, and the decoder flags double
errors as uncorrectable instead of miscorrecting them.

### LDPC codec {#comm-ldpc}

The LDPC codec implements the first rate-1/2 code of IEEE 802.11-2012 Annex F: `n = 648`,
`k = 324`, lifting size `z = 27`, a 12 by 24 base matrix (`LiteDSPLDPCEncoder`,
`LiteDSPLDPCDecoder`). Both are bit-serial at the stream: one bit or one LLR per beat.

The encoder needs no dense generator matrix. The message passes through while twelve 27-bit
accumulators collect one constant rotation per base matrix entry; the dual-diagonal parity part
is then solved one 27-bit block at a time. The cost is about 450 flip-flops and an XOR network.

The decoder runs row-layered normalized min-sum with a factor of 0.75, computed as
`x - (x >> 2)`. It processes the 27 check rows of each layer serially, over a single-port RAM of
the `n` bit values (APP) and compressed check messages: two minima, the index of the first one,
and the signs. All internal widths derive from `llr_bits` (4 by default).

Each check row also computes its syndrome on the fly. An iteration in which every check is satisfied
stops the decoding early with `parity_ok`; otherwise the decoder runs `max_iters` iterations (8 by
default) and counts a failure.

The worst-case schedule is `n + max_iters*z*(2E + 2m_b) + 2k + 4` clocks, 44500 at 8 iterations with
`E = 88` edges and `m_b = 12` layers; each saved iteration removes about 5.4k clocks.

The lift-parallel decoder processes 3, 9 or all 27 rows of a layer together
(`LiteDSPLDPCDecoderZParallel`, `parallelism` 27 by default). It banks the bit values and the
check state by lane, so each cyclic rotation becomes a lane permutation, and it pipelines each
edge through read, rotation, check update and write stages. Its arithmetic and quantization are
bit-exact with the serial decoder.

With 3, 9 and 27 lanes a block takes 36324, 12756 and 4900 clocks at 8 iterations (one iteration
4392, 1464 and 488 clocks, against 5400 for the serial decoder). The 3-lane point is the area
option; early termination shortens the average block time of every architecture. The resources
and clock rates are in [Communications results](#perf-comm).

The serial decoder reaches the following BER on its golden model, with 4-bit LLRs, BPSK in white
noise and 8 iterations: `1.2e-1` at 1.0 dB, `9.8e-3` at 2.0 dB, `6.7e-4` at 2.5 dB, and no error
in the measured blocks at 3.0 dB `Eb/N0`. These are measured on the golden models, as recorded in
`ldpc.py`.

The puncturing matrices `PUNCTURE_*` are in `puncture.py`; every other class is in the file the
[Block list](#comm-list) gives.

## OFDM {#comm-ofdm}

Three blocks complete an OFDM chain around the FFT blocks of [Level control and
analysis](#level-analysis); [OFDM](#cpri-ofdm) explains the method.

The cyclic prefix inserter buffers one `fft_size`-sample symbol and emits it with its last `cp_len`
samples in front (`LiteDSPCPInsert`); the defaults are 64 and 16.

The input stalls while a symbol drains, so the upstream backpressure performs the rate expansion.
The remover drops `cp_len` samples and passes `fft_size` samples framed with `first` and `last` for
the FFT (`LiteDSPCPRemove`), with a latency of 0.

The OFDM equalizer estimates the channel and equalizes each bin with one complex tap
(`LiteDSPOFDMEqualizer`). A pulse on `train` makes the next full frame a training symbol: the
block stores `H_k = Y_k * conj(X_k)` for each bin and outputs nothing. The reference `X_k` is
QPSK, so the estimate needs only additions and subtractions.

The following frames are equalized as `S_k = Y_k * conj(H_k)`, without a divider. The phase is
exact; the amplitude is scaled by `|H_k|**2`, which the block outputs on a `csi` field next to
each bin. A soft demapper weighs its LLRs with it, which is the standard CSI weighting; a hard
decision on QPSK only needs the signs.

The reference RAM holds two sign bits per bin, reset to `1 + 1j` and loaded at run time through
`ref_data`, `ref_we` and `ref_rst`. `H` resets to 1.0 on every bin, so an untrained equalizer passes
the samples unchanged.

Bins are addressed by their position in the frame, so the block works on the bit-reversed output of
the FFT as long as the reference is loaded in the same order.

In the code: `ofdm.py`, `ofdm_eq.py`.

## Timing options {#comm-timing}

The table below summarizes the options of the comm blocks whose feedback loop limits the clock
rate.

| Block | Option | Effect |
|---------------------|------------------------------|-----------------------------------------------|
| Frame synchronizer | `pipelined` architecture | Latency grows by `ceil(log2(N)) + 2` samples |
| Carrier loop | `pipelined` architecture | Loop delay 4 samples, output latency 3 |
| Timing recovery | `pipelined` architecture | 7 settling cycles per symbol instead of 5 |
| Viterbi decoder | `decision_memory` | Decision RAM, folded traceback, input stalls |
| Viterbi decoder | `acs_parallelism` of 32 | Two ACS phases, 2 more clocks per output |
| RS decoder | `pipelined` architecture | `3n + 7t` more clocks per block |
| LDPC decoder | Lift-parallel class | 3, 9 or 27 rows of a layer at once |

The implementation runs select these options for their timing sentinels; the registry and the API
keep the classic defaults, except for the CCSDS Reed-Solomon decoder. [Performance](#performance)
gathers the recorded figures of every block.

## Verification {#comm-verification}

Most comm blocks have a golden model and also run in Verilator co-simulation; the FEC tests cover
the clean, correctable and uncorrectable cases, the ties and the erasures
([Verification](#verification)). The application notes assemble the blocks into complete links
([Examples and application notes](#examples)).

## Block list {#comm-list}

The table lists the 51 registry entries of the family; each name links to its datasheet, which
gives the ports, the parameters, the registers and the recorded resources. Latency is in samples,
"var" when it depends on the data.

| Block | File | Latency |
|------------------------------------------|------------------------|---------|
| [AM modulator][w5b01] | `am_mod.py` | 2 |
| [FM modulator][w5b02] | `fm_mod.py` | 2 |
| [Phase modulator][w5b03] | `fm_mod.py` | 2 |
| [SSB modulator][w5b04] | `ssb_mod.py` | 3 |
| [FSK / GFSK modulator][w5b05] | `fsk_mod.py` | 6 |
| [FM demodulator][w5b06] | `fm_demod.py` | 19 |
| [AM demodulator][w5b07] | `am_demod.py` | 2 |
| [Phase detector][w5b08] | `phase_detect.py` | 19 |
| [Symbol mapper][w5b09] | `mapper.py` | 1 |
| [Slicer][w5b10] | `slicer.py` | 1 |
| [Soft demapper][w5b11] | `soft_demap.py` | 2 |
| [Gray mapper][w5b12] | `gray.py` | 1 |
| [Gray demapper][w5b13] | `gray.py` | 1 |
| [Differential encoder][w5b14] | `diff.py` | 1 |
| [Differential decoder][w5b15] | `diff.py` | 1 |
| [Correlator][w5b16] | `correlator.py` | 3 |
| [Frame sync][w5b17] | `frame_sync.py` | 9 |
| [CFO estimator][w5b18] | `cfo_est.py` | 0 |
| [Carrier loop][w5b19] | `pll.py` | 1 |
| [Timing recovery][w5b20] | `timing_recovery.py` | var |
| [Line encoder (NRZI)][w5b21] | `line_code.py` | 1 |
| [Line decoder (NRZI)][w5b22] | `line_code.py` | 1 |
| [Manchester encoder][w5b23] | `line_code.py` | 1 |
| [Manchester decoder][w5b24] | `line_code.py` | 1 |
| [Scrambler][w5b25] | `coding.py` | 1 |
| [Descrambler][w5b26] | `coding.py` | 1 |
| [CRC][w5b27] | `coding.py` | 1 |
| [HDLC framer][w5b28] | `hdlc.py` | var |
| [HDLC deframer][w5b29] | `hdlc.py` | var |
| [Convolutional encoder][w5b30] | `coding.py` | 1 |
| [Viterbi decoder][w5b31] | `viterbi.py` | 56 |
| [Puncturer][w5b32] | `puncture.py` | var |
| [Depuncturer][w5b33] | `puncture.py` | var |
| [Block interleaver][w5b34] | `interleaver.py` | var |
| [Block deinterleaver][w5b35] | `interleaver.py` | var |
| [Convolutional interleaver][w5b36] | `conv_interleaver.py` | 2 |
| [Convolutional deinterleaver][w5b37] | `conv_interleaver.py` | 2 |
| [RS encoder][w5b38] | `rs.py` | var |
| [RS decoder][w5b39] | `rs.py` | var |
| [CCSDS RS encoder][w5b40] | `rs.py` | var |
| [CCSDS RS decoder][w5b41] | `rs.py` | var |
| [BCH encoder][w5b42] | `bch.py` | var |
| [BCH decoder][w5b43] | `bch.py` | var |
| [Hamming encoder][w5b44] | `hamming.py` | var |
| [Hamming decoder][w5b45] | `hamming.py` | var |
| [LDPC encoder][w5b46] | `ldpc.py` | var |
| [LDPC decoder][w5b47] | `ldpc.py` | var |
| [LDPC decoder (z-parallel)][w5b48] | `ldpc_parallel.py` | var |
| [OFDM CP insert][w5b49] | `ofdm.py` | var |
| [OFDM CP remove][w5b50] | `ofdm.py` | 0 |
| [OFDM equalizer][w5b51] | `ofdm_eq.py` | 2 |

[w5b01]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/am_modulator.md
[w5b02]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/fm_modulator.md
[w5b03]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/pm_modulator.md
[w5b04]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/ssb_modulator.md
[w5b05]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/fsk_modulator.md
[w5b06]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/fm_demod.md
[w5b07]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/am_demod.md
[w5b08]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/phase_detect.md
[w5b09]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/symbol_mapper.md
[w5b10]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/slicer.md
[w5b11]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/soft_demapper.md
[w5b12]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/gray_mapper.md
[w5b13]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/gray_demapper.md
[w5b14]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/diff_encoder.md
[w5b15]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/diff_decoder.md
[w5b16]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/correlator.md
[w5b17]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/frame_sync.md
[w5b18]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/cfo_estimator.md
[w5b19]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/carrier_loop.md
[w5b20]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/timing_recovery.md
[w5b21]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/line_encoder.md
[w5b22]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/line_decoder.md
[w5b23]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/manchester_encoder.md
[w5b24]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/manchester_decoder.md
[w5b25]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/scrambler.md
[w5b26]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/descrambler.md
[w5b27]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/crc.md
[w5b28]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/hdlc_framer.md
[w5b29]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/hdlc_deframer.md
[w5b30]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/conv_encoder.md
[w5b31]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/viterbi_decoder.md
[w5b32]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/puncturer.md
[w5b33]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/depuncturer.md
[w5b34]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/block_interleaver.md
[w5b35]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/block_deinterleaver.md
[w5b36]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/convolutional_interleaver.md
[w5b37]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/convolutional_deinterleaver.md
[w5b38]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/rs_encoder.md
[w5b39]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/rs_decoder.md
[w5b40]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/ccsds_rs_encoder.md
[w5b41]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/ccsds_rs_decoder.md
[w5b42]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/bch_encoder.md
[w5b43]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/bch_decoder.md
[w5b44]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/hamming_encoder.md
[w5b45]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/hamming_decoder.md
[w5b46]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/ldpc_encoder.md
[w5b47]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/ldpc_decoder.md
[w5b48]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/ldpc_decoder_z_parallel.md
[w5b49]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/cp_insert.md
[w5b50]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/cp_remove.md
[w5b51]: https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/ofdm_equalizer.md

The latencies are those of the registry configurations. The Viterbi decoder reports `traceback`, 56,
in its register exchange architecture; its output stream is also `traceback - 1` bits shorter than
its input until tail symbols flush it. With decision memory its latency is variable.

## Where to go next {#comm-next}

[Digital communications](#comm-primer) explains the concepts; [Examples and application
notes](#examples) builds complete links; [Communications registers](#reg-comm) lists the registers
of every block.
