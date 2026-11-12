# Level control and analysis {#level-analysis}

This chapter describes two families. The level blocks scale, limit and measure a signal: gain,
saturation, clipping, squelch, power and RMS meters, logarithms, the AGC loop and the transmit
linearization blocks (DPD, CFR). The analysis blocks turn a stream into measurements: windows, the
FFT family, power spectra, single-bin detectors, statistics and error counts. Read it to choose a
block, to set its parameters and to know what it does at frame boundaries and under backpressure.

The concepts are explained in [Sampled signals and fixed point](#dsp-primer) (dBFS, rounding,
saturation) and in [Oscillators, mixers and the FFT](#spectral-primer) (windows, the SDF FFT,
bit reversal, PSD, Goertzel). The stream rules every block follows are in
[Block contract](#architecture).

## At a glance {#lvl-glance}

| Item | Level control (`litedsp/level/`) | Analysis (`litedsp/analysis/`) |
|------------------|-------------------------------------------|-------------------------------------------|
| Blocks in the registry | 13 | 14 |
| Input | Complex I/Q, except the log blocks (real, unsigned) | I/Q (window, FFT, PSD), real (stats, histogram, Goertzel) |
| Output | Same layout, or one measurement per window | Spectra, frames of bins, or one result per window |
| Control | Registers, plain Signals, sticky flags, IRQ on AGC and squelch | Few registers, IRQ on the energy detector; results on the stream |
| Timing options | AGC feedback delay, CFR pipeline | Folded, interleaved, registered and native FFTs, folded Goertzel |
| Registers | [Level control](#reg-level) | [Analysis and measurement](#reg-analysis) |
| Numbers | [Level control results](#perf-level) | [Analysis results](#perf-analysis) |

Both families are tested in simulation, most blocks against golden models; the status of each
family is in the [status table](#intro-status). Each block also has a datasheet in the
[block catalogue](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md),
with its ports, parameters, registers and recorded resources.

## Level control {#lvl-level}

A level block changes or observes the amplitude of a stream, sample by sample. Most of them share
three idioms of `litedsp/common.py`: products kept at full width, one round-half-up and saturate
step at the output (`scaled`), and a sticky flag that records an overflow until software clears
it. The table below lists the blocks; the sections after it describe them by role.

| Block | Class | Latency | Role |
|-------------|---------------------------------|----------|-------------------|
| Gain | `LiteDSPGain` | 1 | Runtime gain, shift, saturation flag |
| Saturate | `LiteDSPSaturate` | 1 | Fixed shift, round and saturate |
| Clipper | `LiteDSPClipper` | 1 | Hard limit of I and Q to a threshold |
| Squelch | `LiteDSPSquelch` | 1 | Mute below a power, with hysteresis |
| Power meter | `LiteDSPPower` | variable | Mean power over a window, passthrough |
| RMS | `LiteDSPRMS` | variable | Root mean square once per window |
| Envelope detector | `LiteDSPEnvelopeDetector` | 2 | Attack and release envelope follower |
| Log2 | `LiteDSPLog2` | 1 or 2 | Base-2 logarithm of an unsigned value |
| Log power (dB) | `LiteDSPLogPower` | 2 | Power to decibels |
| Exp2 (antilog) | `LiteDSPExp2` | 2 | `2**v` of a log-domain value |
| AGC | `LiteDSPAGC` | 1 | Loop that drives the output level to a target |
| DPD actuator | `LiteDSPDPD` | 4 | Predistortion with per-tap gain LUTs |
| CFR | `LiteDSPCFR` | 1 | Crest-factor reduction by peak cancellation |

The latency is in samples, as `self.latency` publishes it; "variable" means the block emits one
result per window and publishes `None`. The power meter's stream is a zero-latency passthrough,
but it publishes `None` too, so the flow treats it as data dependent. The CFR publishes its
content delay apart from its latency, as [CFR](#lvl-cfr) explains.

### Gain and saturate {#lvl-gain}

The gain block multiplies each I and Q by a signed mantissa and divides by a power of two. The
output is `sample * gain / 2**(gain_frac + shift)`, rounded half up and saturated to `data_width`
bits. The mantissa is a Q2.(N-2) value by default (`gain_frac = data_width - 2`), so 1.0 is
`2**(data_width - 2)` and the largest gain is just under 2.0.

The extra `shift` (0 to 3) divides by 1, 2, 4 or 8, which extends the range downwards without
losing mantissa bits. The block computes the four scaled results in parallel and selects one, so
changing the shift costs no latency. A `bypass` bit passes the input through, and the sticky
`saturation` status bit records any clipped output until `clear_sat` is written.

The saturate block is the same rescale with a fixed shift chosen at build time and no multiplier.
Its input can be wider than its output (`in_width`), so it narrows a grown datapath back to
`data_width` bits with one rounding and one saturation. With `shift=0` it is a saturating
passthrough. It has the uniform `bypass` and the same sticky flag.

The product of the gain block is held in an explicitly sized Signal before the rescale. In the
emitted Verilog, an inline product is sized by its assignment and loses its top bits, while the
Migen simulation keeps full width; the Verilator co-simulation found this, as
[Verification](#verification) describes.

### Clipper and squelch {#lvl-clipper}

The clipper clamps I and Q independently to plus or minus a runtime `threshold`, full scale by
default. It clips each component, not the magnitude, so a clipped complex sample may change
phase. The `clip` output pulses on each clipped sample and is visible in the `status` register;
the block has the uniform `bypass`.

The squelch mutes a stream whose instantaneous power `I**2 + Q**2` is low. It opens when the power
reaches `open_threshold` and closes when it falls below `close_threshold`; setting the close
threshold under the open one gives hysteresis. When closed, it outputs zeros and keeps the sample
rate, so the stream timing downstream does not change.

The gate state changes only on accepted samples and holds during stalls. With `with_irq=True`,
the squelch raises an `opened` interrupt on the opening edge and a `closed` interrupt on the
closing edge. Both thresholds are power values, `2*data_width + 1` bits wide.

### Power, RMS and envelope {#lvl-measure}

The power meter passes the stream through unchanged, with no added delay (its `latency` is `None`),
and measures it on the side. It sums `I**2 + Q**2` over `2**window_log2` accepted samples, then
latches the block average into `power` and pulses `update`. The window is a runtime register
(`window`), bounded by `max_window_log2` (20 by default), which sizes the accumulator.

The RMS block computes `sqrt(mean(I**2 + Q**2))` over a window and emits one value per window on
its source, through a small sequential square root (`LiteDSPISqrt`). Its sink is always ready.

The block is an exception to full backpressure. It hands each result to the square root as a
one-cycle pulse, without checking that the square root is ready. A window shorter than about 18
samples (the square-root run), or a consumer stalled until the next window ends, loses that result
([Known issues](#intro-known-issues)).

The envelope detector follows `|I + jQ|`, estimated by the alpha-max-beta-min magnitude, with a
single-pole smoother: `env += (|x| - env) >> attack` while the level rises and `>> release` while it
falls. The time constants are about `2**attack` and `2**release` accepted samples; a large release
approximates a peak-hold detector. It outputs the envelope as a real stream.

### Logarithm and antilogarithm {#lvl-log}

Level loops and meters often work in decibels. `LiteDSPLog2` finds the most significant set bit of
an unsigned input with a priority encoder and takes the bits below it as the fraction. This linear
approximation has an error under about 0.086, that is 0.26 dB on a power and 0.52 dB on an
amplitude.

With `lut=True` a ROM of `log2(1 + m)`
refines the fraction to under `2**-frac_bits`, at one more clock; the audio dynamics and meter
blocks use it.

The output is unsigned, with enough integer bits for the bit index and `frac_bits` fractional
bits (8 by default); an input of zero gives zero. `LiteDSPLogPower` multiplies this result by
3.0103 dB per bit to give decibels of a power value with `out_frac` fractional bits.

`LiteDSPExp2` is the inverse: it computes `2**v` of a signed log-domain value. A ROM gives the
fractional part, the integer part shifts it, saturating at the top and rounding at the bottom. It
turns a gain computed in decibels back into a linear multiplier, as the audio compressor does.

### AGC {#lvl-agc}

The automatic gain control multiplies the stream by a gain and adjusts the gain so that the output
magnitude approaches a `target`. The figure below shows the two halves: the datapath on top, which
handles one sample per clock, and the gain loop below, which updates the gain once per accepted
sample.

![AGC: the gain multiplies the stream; the magnitude of the output, delayed by 0, 1 or 2 accepted
samples, drives the error that integrates into the clamped gain register.](lvl_agc.svg)

The loop is a clamped integrator. The output magnitude is estimated as `max(|I|, |Q|) + min(|I|,
|Q|) >> beta_shift` (2 by default, between -12 % and +3 % error, no multiplier). Each accepted
sample adds `(target - |y|) >> mu` to the gain, which is then clamped to `[0, gain_max]`. A larger
`mu` gives a slower and smoother loop; a smaller one acquires faster but may pump on modulated
signals.

The gain register has `data_width + gain_frac` bits, with 1.0 at `2**gain_frac`, its reset value.
`gain_max` defaults to the full register range; lower it to bound the gain on silence. The
`railed` signal is high while the gain sits at a clamp, that is on overload or underrange, and
with `with_irq=True` its rising edge raises the `railed` interrupt.

| Parameter | Default | Effect |
|-------------------------|------------------------|----------------------------------------------|
| `gain_frac` | 8 | Fractional bits of the gain; width of the multiplier |
| `mu` | 8 | Loop gain `2**-mu`: time constant of the loop |
| `gain_max` | full gain register | Upper clamp of the gain |
| `beta_shift` | 2 | Beta of the magnitude estimate |
| `feedback_delay` | `None` (0) | Accepted samples between the output and the gain update |
| `with_irq` | `False` | Interrupt on the rising edge of `railed` |

The registers are `target` (the magnitude to reach, `2**(data_width - 2)` at reset, half of full
scale), `gain` (the current gain, read only) and `config` (the feedback delay of the build). The
gain integrates only on accepted samples, so the loop pauses with the stream and its trajectory
does not depend on stalls.

#### AGC timing options {#lvl-agc-timing}

In the classic loop, the same accepted transfer applies `gain[n]`, measures `|y[n]|` and commits
`gain[n+1]`. The multiply and rescale, the magnitude, the error and the clamp form one
combinational path, which limits the clock rate. A register inside that loop changes
the gain trajectory, so the faster loops are explicit options of `feedback_delay`.

| Delay | Loop | Datapath | Use |
|-----------------|-------------------------------------------------|------------------------|---------------------------|
| 0 | Gain from the magnitude of the sample being registered | 1 sample per clock, latency 1 | Registry default, compatibility |
| 1 | Gain from the registered output, one sample later | Same | Smallest change |
| 2 | Max and min components registered, magnitude formed on the gain side | Same | Implementation configuration |

The two-sample option registers the max and min components and forms the magnitude on the gain
side, which adds one more sample of loop delay without changing the datapath latency or rate. A
two-entry observation queue keeps the loop exact in the sample domain: when the consumer drains an
output during an input gap, its magnitude is kept until the next accepted sample.

The `delayed_feedback=True` argument selects one sample; the implementation registry selects
`feedback_delay=2`. [Timing architecture](#perf-timing-arch) gives the results of each option and
[Quality characterization](#perf-quality) the settling of the two-sample loop on the golden model.

### DPD actuator {#lvl-dpd}

Digital predistortion pre-distorts the transmit signal with the inverse of the power amplifier
distortion, so that the amplifier output is linear. `LiteDSPDPD` is the fabric half of a DPD
system: it applies a memory-polynomial correction, and the host computes the correction from
captured data. This keeps the sample-rate datapath at a few multipliers and LUT RAMs.

The actuator computes `y[n] = sum_m x[n-m] * G_m(|x[n-m]|)` for `m = 0..n_taps-1`. Each branch
multiplies a delayed sample by a complex gain read from that branch's LUT, addressed by the
sample's own magnitude. Tap 0 corrects the memoryless AM/AM and AM/PM distortion; the other taps
correct mild memory effects of the amplifier.

The magnitude uses a two-region estimate, `max(hi, hi - hi/8 + lo/2)`, with about 3 % peak error;
its top `log2(lut_depth)` bits below full scale address the LUT. The entries are complex signed
Q2.`coeff_frac` pairs, so a gain can exceed 1 to expand a compressing amplifier. The LUTs start
as the identity (tap 0 at 1.0, other taps at 0), so an untrained block is an exact passthrough.

| Parameter | Default | Effect |
|--------------|---------|-----------------------------------------------------|
| `n_taps` | 3 | Memory depth: one LUT and one complex multiplier per tap |
| `lut_depth` | 64 | Entries per LUT (magnitude bins), power of two |
| `coeff_frac` | 14 | Fractional bits of the entries and of the output rescale |

Software writes the LUTs through a sequential port: select a tap (`lut_tap`), reset the entry
pointer (`lut_reset`), then write `lut_depth` packed `{Q, I}` entries to `lut`. Write while the
stream is idle or bypassed, since entries take effect as written. The latency is 4 clocks:
magnitude, index, LUT read and complex multiply, sum and scale.

The host side is `DPDAdapter` in `litedsp/software/dpd.py`. It fits the LUTs by indirect learning:
capture time-aligned records of the amplifier input and output with the capture blocks, call
`fit()`, then `program()` to write the LUTs. One or two iterations of capture and fit converge,
each refitting on the already predistorted amplifier.

### CFR {#lvl-cfr}

Crest-factor reduction lowers the peak-to-average power ratio of a signal such as OFDM, so that the
amplifier can run closer to its limit. `LiteDSPCFR` subtracts a scaled low-pass pulse centred on
each peak above a runtime `threshold`. The pulse keeps the correction energy inside the signal
band, which bounds the damage to the adjacent channels and to the EVM.

The block detects local maxima of the alpha-max-beta-min magnitude, with one sample of lookahead.
For a peak `x_pk` it scales the pulse by `g = (|x_pk| - T)/|x_pk|`, so the corrected peak lands
near T. The division is replaced by a 64-entry reciprocal table on the normalized magnitude, with
about 0.8 % relative error, well inside the error of the magnitude estimate itself.

A single pulse engine plays one pulse of `pulse_span + 1` samples at a time. Peaks found while it
is busy pass uncorrected and are counted: the `peaks` register counts corrected peaks and `missed`
the skipped ones. The signal goes through a delay line of `pulse_span/2 + 2` samples (`self.delay`,
10 by default) so that the pulse centre lines up with the peak.

`self.latency` is the pipeline depth, 1; the content delay is published apart as `self.delay`, like
the group delay of a FIR. The flow balances paths with `latency` only: a parallel branch that must
line up with the content of the CFR output adds `self.delay` by hand.

`architecture="pipelined"` registers the normalization, the reciprocal multiply and the amplitude
multiply, keeping one sample per clock; it adds four samples to the matched delay and reserves the
engine while a coefficient is in flight ([results](#perf-level)). The `cutoff` parameter sets the
pulse bandwidth: set it to the one-sided bandwidth of the signal.

The `cfr_pulse()` and `cfr_recip_lut()` functions of `litedsp/level/cfr.py` build the pulse and
the table; the golden model in `test/models.py` uses the same geometry. On the golden model, the
characterization stimulus loses 1.567 dB of PAPR; the residual is set by skipped peaks and by the
magnitude estimate.

## Analysis {#ana-analysis}

The analysis blocks measure a stream. Some are transforms that output a frame per input frame
(window, FFTs); the others reduce a window of samples to a result (PSD, Goertzel, statistics,
histogram) or watch a stream on the side (detectors, error counter).

| Block | Class | Latency | Role |
|-------------|-------------------------------|----------|---------------------|
| Window | `LiteDSPWindow` | 2 | Multiply each frame by a window |
| FFT (SDF) | `LiteDSPFFT` | N-1 | Streaming radix-2 FFT, bit-reversed |
| FFT (iterative) | `LiteDSPFFTIter` | burst | In-place FFT in block RAM, natural order |
| FFT (parallel) | `LiteDSPParallelFFT` | fixed | FFT at P samples per clock |
| Bit-reverse reorder | `LiteDSPBitReverse` | frame | Bit-reversed to natural order |
| PSD | `LiteDSPPSD` | variable | Power spectrum, averaged or held |
| Welch PSD | `LiteDSPWelchPSD` | variable | Window, FFT and PSD with overlap |
| Magnitude | `LiteDSPMagnitude` | 1 or 19 | Approximate or CORDIC magnitude |
| Goertzel | `LiteDSPGoertzel` | variable | Power of one DFT bin |
| Stats | `LiteDSPStats` | 1 | Min, max, mean, variance per window |
| Histogram | `LiteDSPHistogram` | variable | Sample distribution per window |
| Energy detector | `LiteDSPEnergyDetector` | 0 | Presence over an adaptive floor |
| Error counter | `LiteDSPErrorCounter` | variable | Mismatches between two streams |

Two more classes of `litedsp/analysis/` are exported but not in the registry, so the flow tool
and the GUI do not offer them: `LiteDSPPeakBin` and `LiteDSPFrequencyEstimator`, described in
[Detectors and counters](#ana-detect).

### Window {#ana-window}

`LiteDSPWindow` multiplies each sample by the real coefficient of its position in a frame of `n`
samples, with round and saturate. The window is fixed at build time: `rect`, `hann` (default),
`hamming` or `blackman`, quantized to Q1.(N-1) by `window_coefficients()`. The block marks each
frame with `first` and `last`, and `n` must match the size of the FFT that follows.

The multiplier outputs are registered before the rescale, so the latency is 2 clocks at one sample
per clock. On the golden model, a 64-point Hann window has a peak sidelobe 31.471 dB below its main
lobe.

### FFT family {#ana-fft}

LiteDSP has three FFT engines with timing options. The figure below sorts them by the way they
move samples; the darker boxes are the timing-oriented options that close the 100 MHz objective.

![FFT family: streaming SDF engines on the left, the iterative burst engine in the middle and the
P-lane engines on the right; the darker boxes are the timing-oriented options.](ana_fft_family.svg)

All engines are radix-2, use `N` as the transform size (a power of two) and scale by 1/2 per rank,
1/N overall, unless block floating point is selected. Their twiddles are signed
Q1.(`twiddle_width`-1) values, 16 bits by default. The table below compares them; the latencies
are those the blocks publish.

| Engine | Throughput | Output order | Framing out |
|----------------|--------------------|------------------|-------------------|
| SDF classic | 1 sample per clock | Bit-reversed | Positional |
| SDF folded | 1 per 2 clocks | Bit-reversed | Positional |
| SDF interleaved | 1 per clock, 2 contexts | Bit-reversed | Positional |
| Iterative | One frame per burst | Natural | `first`, `last` |
| Parallel split | 2 per clock | Bit-reversed, 2 lanes | `first`, `last` |
| Parallel native | 2 or 4 per clock | Bit-reversed, P lanes | `first`, `last` |

#### SDF FFT {#ana-fft-sdf}

`LiteDSPFFT` cascades `log2(N)` single-path delay-feedback stages (`LiteDSPFFTStage`). Stage `k`
has a delay line of `N >> (k+1)` samples: during the first half of each block it stores the input
and outputs the previous twiddled difference, during the second half it outputs the butterfly sum
and stores the new difference ([The FFT](#pri-fft)). The output is in bit-reversed order;
`bit_reverse()` gives the index of each bin.

Frames are positional. The FFT counts samples from reset and does not carry `first` or `last`
through its pipeline, so its source has no frame markers. The first `N-1` outputs after reset are
pipeline fill (`self.latency`). `LiteDSPPSD` skips exactly that many by default before counting
frames; `LiteDSPBitReverse` does when its `fft_latency` is set to N-1. Feed whole frames from reset,
or reset the chain to realign it.

`architecture="folded"` replaces each stage by `LiteDSPFFTFoldedStage`, which spreads the
butterfly over three pipeline edges and accepts one sample every two clocks. It is bit-identical
to the classic scaled mode. `LiteDSPInterleavedFFT` alternates accepted samples between two folded
FFTs, which restores one aggregate sample per clock for two independent interleaved streams.

#### Block floating point {#ana-fft-bfp}

With `scaling="bfp"` each stage halves a frame only when needed. All butterflies of frame k are
halved when any butterfly of frame k-1 overflowed `data_width` bits unshifted; frame 0 is not
halved. Small signals therefore keep up to `log2(N)` extra bits, about 6 dB each.

The source then carries a 5-bit `exp` parameter field, constant over each output frame: the
number of halvings applied, so the output is `DFT(x) / 2**exp`. With `exp == log2(N)` the result
is bit-identical to scaled mode. When a frame grows faster than the previous one predicted, it
saturates, as in scaled mode. The folded architecture supports scaled mode only.

The PSD and magnitude blocks ignore parameter fields and consume a BFP frame unnormalized. Connect
a BFP source to a sink without `exp` by passing `omit={"exp"}` to `connect()`.

#### Iterative FFT {#ana-fft-iter}

`LiteDSPFFTIter` runs a single butterfly in place on two block RAMs, one for I and one for Q, each
a true dual-port memory with synchronous reads. It loads a frame in bit-reversed address order,
runs `log2(N)` ranks of `N/2` butterflies, then reads the frame out in natural order with `first`
and `last`. It does not accept input while it computes and unloads, so it suits bursts and low
sample rates.

Each butterfly takes three clocks: read, twiddle product, write. `registered_butterfly=True` adds
a fourth clock that registers the sums and differences before the write. With k the clocks per
butterfly, a frame takes `N + k*N*log2(N)/2 + 2*N` clocks (`cycles_per_frame`): N to load, the
butterflies, and two clocks per sample to unload (`UNLD_READ`, then `UNLD_EMIT`). The `latency`,
from the first input to the first output as for `LiteDSPFFT`, is `(N - 1) + k*N*log2(N)/2 + 2`.
At N=16 these are 144 and 113 clocks (176 and 145 with the registered butterfly); at N=256, 3840
and 3329 clocks (4864 and 4353).

#### Parallel FFT {#ana-fft-parallel}

`LiteDSPParallelFFT` processes P samples per clock, for sample rates above the clock rate. Both
implementations are bit-identical to the serial SDF FFT on the flattened lane stream: every
rounding happens at the same place. Lane 0 is the oldest sample of a beat, and a frame is `N/P`
beats with `first` and `last` on its first and last beats.

The default `implementation="split"` supports P=2. A first butterfly rank splits each frame into a
sum half-frame (even bins) and a twiddled difference half-frame (odd bins), and two unmodified
serial FFTs of size N/2 process them. With `core_architecture="folded"` it uses folded sub-cores,
which halves the average rate to one sample per clock.

`implementation="native"` advances a single SDF feedback line by P samples per clock, for P=2 or
P=4, without the split version's FIFOs, serializers and duplicated cores. `feedback_pipeline=True`
registers the butterfly difference and the twiddle products in the ranks with at least two packed
feedback addresses, and forwards same-address values so the recurrence stays exact. Native P=4
also offers `complex_multiplier="three"`, which uses three real multipliers per complex product.

#### FFT timing options {#ana-fft-timing}

In an SDF stage the twiddled difference is multiplied, scaled and written into the delay feedback
on the same beat; the iterative core has the same read, butterfly and write schedule in RAM. A
register in either loop changes which operands meet, unless the schedule or the number of
contexts changes too. Each timing option therefore changes one of them.

The folded SDF stage registers the butterfly difference and the four real twiddle products, and
overlaps the completion with the next capture; a same-address bypass keeps the depth-one feedback
exact. At N=256 this adds one clock per rank and keeps the two-clock interval. The interleaved
FFT restores one aggregate sample per clock for two contexts, and the registered iterative
butterfly lengthens the frame from 3584 to 4608 clocks at N=256.

The split parallel FFT inherits its SDF choice through `core_architecture`. In the native engine,
`feedback_pipeline=True` registers the arithmetic loop and puts a ready-only skid buffer in the
middle of the cascade; the buffer holds one P-wide beat only during a downstream stall and leaves
the latency, the arithmetic and the rate unchanged. At P=2 the option costs seven clocks of
latency.

The three-multiplier option uses the Gauss identity `k1 = c(a+b)`, `k2 = a(d-c)`, `k3 = b(c+d)`,
then `real = k1 - k3` and `imag = k1 + k2` at full precision, before the same rounding. It saves
DSP blocks on ECP5 and UltraScale+ but not on Artix-7, where the four-multiplier default is the
better choice. Every option is bit-identical to `fft_fixed_model` in scaled mode;
[Timing architecture](#perf-timing-arch) gives the recorded results, and
[Analysis results](#perf-analysis) those of every configuration.

#### Bit-reverse reorder {#ana-bitrev}

`LiteDSPBitReverse` turns the bit-reversed output of an SDF FFT into natural order. It writes each
frame of N beats at the bit-reversed address of its position in one half of a two-frame RAM, and
reads the other half sequentially with `first` and `last`. After the first frame, a continuous
stream flows at one beat per clock. Set `fft_latency` to the FFT latency, as for the PSD; any
payload layout is carried as raw bits.

### Spectrum: PSD and Welch {#ana-psd}

`LiteDSPPSD` turns FFT frames into a power spectrum ([Power spectral density and
Welch](#pri-psd)). It computes `|X[k]|**2 = I**2 + Q**2` for each
bin, combines it with the previous frames in an accumulator RAM of N bins, and every
`2**avg_log2` frames emits the spectrum in natural bin order, framed with `first` and `last`.
While it emits, it backpressures the FFT, so no sample is lost. The figure below shows the PSD
inside the Welch composite.

![Welch PSD: the overlap replay feeds the window and the SDF FFT; the PSD squares, combines and
accumulates each bin, then reads the spectrum out in natural order.](ana_psd.svg)

The combining mode is a runtime field of the `control` register. The emission cadence is the same
in all modes; a `clear` pulse makes the next frame overwrite the accumulator instead of combining
with it, which resets a hold or an exponential trace.

| Mode | Value | Combining | Accumulator |
|----------------|-------|-------------------------------------------|-------------------------------|
| Linear average | 0 | Sum of `2**avg_log2` frames, `>> avg_log2` | Restarts with each spectrum |
| Exponential | 1 | Leaky average, step `>> avg_log2` | Persists across spectra |
| Max-hold | 2 | Per-bin maximum | Persists until cleared |
| Min-hold | 3 | Per-bin minimum | Persists until cleared |

The PSD skips the first `fft_latency` samples after reset, `N-1` by default to match
`LiteDSPFFT`, so that bin 0 lines up with a frame start. Its output is `2*data_width + avg_log2`
bits wide. It reads FFT frames unnormalized, so a BFP FFT needs its `exp` field handled apart.

`LiteDSPWelchPSD` chains a window, an SDF FFT and a PSD, with the FFT latency set for the PSD. With
`overlap` at 25, 50 or 75 %, successive segments share `N*overlap/100` samples, which must be an
integer. After each segment, the shared tail is replayed from a history RAM into the window while
the input stalls.

The replay runs at the clock rate, so the sustained input rate with overlap is bounded by about
`f_clk * (1 - overlap/100)`, minus the PSD readout stalls. With `overlap=0` (the default) the chain
streams at one sample per clock. Its registers are those of the PSD, prefixed `psd_`. The spectrum
monitor application note in [Examples](#examples) uses this block with timestamps.

### Magnitude {#ana-magnitude}

`LiteDSPMagnitude` computes `|I + jQ|` in two ways. `method="approx"` (default) uses
alpha-max-beta-min, `max + min >> beta_shift`, without multiplier, with an error between about
-12 % and +3 %, in one clock. `method="cordic"` uses a CORDIC in vectoring mode: exact to its
precision, with a latency of 19 clocks at 16 bits. The output is one bit wider than the input,
since a magnitude reaches about 1.41 times full scale.

### Goertzel {#ana-goertzel}

The Goertzel block measures the power of one DFT bin with one multiplier, which is cheaper than a
full FFT for a few tones, such as DTMF or a pilot ([Goertzel](#pri-goertzel)). For bin `k` of an
`N`-sample window it runs the resonator `s = x + coeff*s1 - s2`, with `coeff = 2*cos(2*pi*k/N)` in
`coeff_frac` fractional bits. After N samples it emits `s1**2 + s2**2 - coeff*s1*s2` and restarts.

The detected frequency is `k * f_sample / N`. The state is `data_width + coeff_frac + 4` bits wide
and the result twice that. The classic architecture is always ready. `architecture="folded"`
splits the resonator over two clocks and accepts one sample every two clocks, for a higher clock
rate ([Analysis results](#perf-analysis)). The `config` register returns the bin.

### Statistics and histogram {#ana-stats}

`LiteDSPStats` measures a real stream over windows of `2**window_log2` samples and emits one record
per window with `min`, `max`, `mean` and `variance`, the variance computed as `E[x**2] - E[x]**2`.
Its input is always accepted. A result is held until consumed; a result not read before the next
window ends is replaced.

`LiteDSPHistogram` counts samples per bin over `2**window_log2` samples, binning by the top `bits`
of the sample in offset binary, for `2**bits` bins. It then streams the counts in natural order,
framed, while it backpressures its input; each bin is cleared as it is read. It suits ADC
characterization, where the shape of the distribution shows missing codes and clipping.

### Detectors and counters {#ana-detect}

The energy detector passes the stream through without latency and raises `detect` while the
instantaneous power exceeds the noise floor by `2**threshold_log2`, about 3 dB per step. The floor
is a leaky average, `floor += (power - floor) >> avg_shift`, updated only while no signal is
detected. It starts high and converges down to the noise, which avoids a floor stuck at zero. With
`with_irq=True` a detection edge raises an interrupt.

The error counter compares a reference stream and a received stream in lock step: it consumes a
pair only when both are valid, counts the pairs (`total`) and the mismatches (`errors`), and clears
both on a write to `clear`.

The k-th samples of the two inputs always meet, whatever the latency
of each branch; unequal latencies only lower the throughput.

It measures a bit or symbol error rate when the reference is a replay of the transmitted data.
[Debugging](#debugging) uses it to locate a broken stage.

`LiteDSPPeakBin` finds the largest value of each framed real stream, such as a PSD frame, and emits
its index and value at the end of the frame. `LiteDSPFrequencyEstimator` also emits the two
neighbours of the peak, so that firmware can interpolate a sub-bin frequency with a three-point
parabola and keep the division in software. Both need `first` and `last` on their input.

## Verification of these families {#lvl-verification}

Each block is tested in the Migen simulation under randomized backpressure, most of them against
a golden model of `test/models.py`; `test/registry.py` records which check covers which block,
and [Verification](#verification) describes the method. The SDF FFT also runs in Verilog inside
the Welch co-simulation. The AGC, the clipper, the CFR and the window have quality metrics
measured on the golden models and gated nightly ([Quality characterization](#perf-quality)).

## In the code {#lvl-code}

Each class lives in `litedsp/level/` or `litedsp/analysis/`, in a file named after the block
(`gain.py`, `agc.py`, `fft.py`, `psd.py`). The exceptions are `peak.py` (envelope detector),
`logdb.py` (log2, log power, exp2), `fft_parallel.py` (also `LiteDSPNativeParallelFFT`),
`reorder.py` (bit reverse), `detect.py` (energy detector, frequency estimator), `peak_bin.py`
(`LiteDSPPeakBin`) and `measure.py` (error counter).

Next: [Communications blocks](#comm) for the receivers that use these blocks, and
[Performance and resources](#performance) for the numbers of every configuration.
