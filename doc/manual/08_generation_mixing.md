# Generation, mixing and correction {#generation-mixing}

This chapter describes the blocks that make signals, move them in frequency and clean up the
impairments of a radio front end: the generation family (`litedsp/generation/`), the mixing family
(`litedsp/mixing/`) and the correction family (`litedsp/correction/`), plus the parallel variants
of the NCO, the mixer and the DDC. Read it to choose an oscillator, tune a down-converter, split a
band into channels or correct the DC offset and I/Q imbalance of a converter.

The theory is in Part I: the NCO, CORDIC, complex mixing and the DDC in
[Oscillators, mixers and the FFT](#spectral-primer), fixed-point rescaling in
[Sampled signals and fixed point](#dsp-primer). Every block follows the stream, latency, bypass
and register conventions of [the block contract](#architecture), which this chapter does not
repeat. The maturity of each family is in the [status table](#intro-status).

## At a glance {#gm-glance}

| Block | Class | Latency | Registers |
|-----------------|--------------------------------|---------|------------------------|
| NCO | `LiteDSPNCO` | 1 | `phase_inc` |
| CORDIC | `LiteDSPCORDIC` | 19 | `latency` |
| Chirp | `LiteDSPChirp` | none | `start`, `rate` |
| Noise (AWGN) | `LiteDSPNoiseSource` | none | none |
| Pattern source | `LiteDSPPatternSource` | none | `control`, `const` |
| Mixer | `LiteDSPMixer` | 2 | `control` |
| DDC | `LiteDSPDDC` | 3 | NCO, decimator |
| DUC | `LiteDSPDUC` | 3 | NCO, interpolator |
| Channelizer | `LiteDSPChannelizer` | 36 | none |
| PFB channelizer | `LiteDSPPFBChannelizer` | 60 cycles | `config` |
| DC offset | `LiteDSPDCOffset` | 1 | none |
| I/Q balance | `LiteDSPIQBalance` | 1 | `c1`, `c2`, sums |
| Derotator | `LiteDSPDerotator` | 2 | `nco_phase_inc` |

Latencies are in samples with the registry parameters, as the catalogue prints them; "none" marks a
source, whose output does not follow an input. The PFB channelizer publishes clock cycles per frame.
The DDC, DUC and channelizer values include their mixer (see [DDC](#gm-ddc)). The full register
lists are in the appendix: [generation](#reg-generation), [mixing](#reg-mixing) and
[correction](#reg-correction). Each block also has a datasheet in the [block
catalogue](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md).

## Generation {#gm-generation}

The generation family holds the stream sources of LiteDSP: the NCO, which every mixer, DDC and
DUC uses as its local oscillator, the CORDIC, and the test and stimulus sources. A source has no
sink. It presents a sample, keeps it until the next block accepts it, and only then computes the
next one, so backpressure never drops or repeats a sample.

### NCO {#gm-nco}

The NCO (numerically controlled oscillator, also called DDS) produces the complex exponential
`cos + j sin` at a frequency set by one register. The primer explains the principle in
[The NCO](#pri-nco); this section describes how `LiteDSPNCO` implements it.

The figure below shows the datapath. A phase accumulator adds the phase increment for every
accepted sample. Its top bits address a cosine ROM and a sine ROM, whose registered outputs are
the I and Q of the source.

![NCO datapath: the phase increment register drives the phase accumulator, whose top bits address
the cosine and sine ROMs; the accumulator advances only when the output can accept a
sample.](gen_nco.svg)

The output frequency follows from the increment. With `phase_bits` bits of phase and a sample
rate `fs`, the frequency is `phase_inc * fs / 2**phase_bits`; an increment in the upper half of
the range is a negative frequency. The NCO advances once per accepted sample, so `fs` is the rate
at which the next block takes samples: the clock rate when it takes one on every cycle.

```python
# Increment for a tone at f_out, as the host driver computes it.
phase_inc = round(f_out/fs * 2**32) & 0xffffffff
```

The host driver does this conversion: `NCODriver.set_frequency()` in
`litedsp/software/drivers.py` writes the increment for a frequency in Hz, given the clock
frequency. The same driver binds the NCO inside a DDC or a DUC at its register prefix.

The ROM depth sets the spurs. Only the top `log2(lut_depth)` bits of the phase address the ROM, so
the truncated phase bits produce spurs, as [Phase truncation and spurs](#pri-nco-spurs) explains.
The characterization of the default NCO (`lut_depth=1024`, 32-bit phase, 16-bit I/Q) records the
following values, measured on the golden models (`char/results.json`):

| Metric | Value | Condition |
|------------------------|--------------|------------------------------------------|
| SFDR | 58.611 dB | Worst case over a sweep of `phase_inc` |
| SFDR, LUT-exact | 103.473 dB | Increments that hit ROM entries exactly |
| ENOB | 8.85 bits | Worst case over the sweep |
| Noise floor | -52.025 dBFS | Worst case over the sweep |

The gap between the two SFDR lines is the cost of phase truncation. An increment that is a
multiple of `2**(phase_bits - 10)` addresses the ROM without truncation and is limited only by
the 16-bit amplitude quantization. A deeper ROM lowers the truncation spurs at the cost of memory.

The quarter-wave option (`quarter_wave=True`) stores a single sine table of `lut_depth/4 + 1`
entries and rebuilds the cosine and the sine from the quadrant bits by symmetry. The output is the
same as with the two full tables of `lut_depth` words each, for about an eighth of the memory and a
few multiplexers.

The NCO is a free-running source. Its `valid` rises once the first sample is in the output
register and stays high; the accumulator advances only on a clock where the output is free or
being accepted. When the NCO feeds a mixer, the mixer takes an NCO sample only together with an
input sample, so the oscillator stays in step with the signal under any backpressure.

| Parameter | Default | Effect |
|------------------|----------|------------------------------------------------------|
| `phase_bits` | 32 | Width of the accumulator and of `phase_inc` |
| `data_width` | 16 | Width of I and Q, full scale Q1.15 |
| `lut_depth` | 1024 | ROM depth, a power of two; sets the truncation spurs |
| `quarter_wave` | `False` | One quarter-wave sine table instead of two full ROMs |

In the code: `LiteDSPNCO` in `litedsp/generation/nco.py`. The same file holds `sincos_rom()`,
the ROM lookup that the motor-control sine/cosine block shares with the NCO.

### CORDIC {#gm-cordic}

The CORDIC rotates a vector by an angle, or measures the magnitude and the angle of a vector,
with shifts and additions only ([CORDIC](#pri-cordic)). `LiteDSPCORDIC` is fully pipelined: one
iteration per stage, one sample per clock, and backpressure freezes the whole pipeline.

| Mode | Input fields | Output fields | Use |
|------------------|----------------|------------------|----------------------------------|
| `"rotation"` | `x`, `y`, `z` | `x`, `y` | Rotate `(x, y)` by `z`; sine/cosine |
| `"vectoring"` | `x`, `y` | `mag`, `angle` | Magnitude and `atan2(y, x)` |

Angles are signed and the full circle spans `2**angle_width`, so pi is `2**(angle_width - 1)`. A
pre-rotation stage brings the input into the convergence range of the iterations. In rotation mode
it rotates by pi when the angle is beyond plus or minus pi/2; in vectoring mode it rotates a vector
with a negative `x` by pi (negates `x` and `y`) and starts the angle at plus or minus pi. The CORDIC
then converges over the full circle.

The iterations multiply the magnitude by the CORDIC gain K, about 1.65. The block multiplies the
result by the constant 1/K in Q1.15 and rescales it with rounding and saturation, so rotation and
magnitude have unity gain. The internal datapath carries two guard bits; `mag` is one bit wider
than the inputs.

The latency is `stages + 3` clocks: the pre-rotation register, one register per iteration, the
product by 1/K and the output register. With the defaults (`stages` and `angle_width` equal to
`data_width`, 16) this is 19, which the `latency` status register reports.

Each stage adds about
one bit of precision. The characterization records an ENOB of 12.705 bits in rotation mode with
16-bit data and 16 stages, measured on a Migen simulation of the block.

In the code: `LiteDSPCORDIC` and `cordic_gain()` in `litedsp/generation/cordic.py`.

### Chirp {#gm-chirp}

The chirp source produces a linear frequency sweep, for radar pulses and calibration sweeps. Two
accumulators run in cascade: the frequency accumulator adds `rate` per sample, and the phase
accumulator adds the frequency. The phase addresses cosine and sine ROMs as in the NCO.

The sweep starts at the frequency word `start` on the first sample and then ramps by the signed
`rate` per sample, both in the phase units of the NCO. The block has no stop: it keeps sweeping
and wraps around the phase circle. A host or a gating block decides the length of a pulse. The
ROM reads are asynchronous, so the I/Q follow the phase register directly.

| Register | Width | Meaning |
|----------|-------|------------------------------------------|
| `start` | 32 | Initial frequency word |
| `rate` | 32 | Frequency increment per sample (signed) |

In the code: `LiteDSPChirp` in `litedsp/generation/source.py`.

### Noise source {#gm-noise}

The noise source produces approximately Gaussian complex noise, for bit error rate and AWGN
testbenches. Each axis sums `n_sum` independent xorshift32 generators (16 by default). By the
central limit theorem the sum of uniform values approaches a normal distribution.

The top `data_width` bits of each generator are taken as a signed sample, the samples are added,
and the sum is shifted right by `shift` (2 by default) to set the level. The seeds derive from
`seed`, so the sequence is the same on every run. The level and the seed are build-time
parameters: the block has no register, and its `with_csr` argument is unused.

The output standard deviation is about `sqrt(n_sum/3)*2**(data_width - 1)/2**shift`. The shifted
sum saturates at full scale: with the defaults about 9 % of the samples are clipped, so use
`shift` = 3 or more (a standard deviation of about 9500 LSB) for an unclipped Gaussian output.

In the code: `LiteDSPNoiseSource` in `litedsp/generation/source.py`.

### Pattern and replay sources {#gm-pattern}

The pattern source is a bring-up and loopback tool. It emits one of four patterns on an I/Q
stream, selected at run time by the `mode` field of the `control` register:

| Mode | Value | I | Q |
|------------|-------|---------------------------------|----------------------|
| `const` | 0 | `const` register, field `i` | Field `q` |
| `counter` | 1 | Incrementing counter | Inverted counter |
| `prbs` | 2 | Maximal-length LFSR | Inverted LFSR |
| `impulse` | 3 | One full-scale sample, then 0 | 0 |

The PRBS is a Galois LFSR seeded by `seed` (forced to non-zero), with a primitive feedback
polynomial for each `data_width` from 3 to 32 bits, so its period is `2**data_width - 1`. It
serves error counting between two copies of the same stream, as the loopback example
`examples/loopback_ber.py` does ([the examples](#examples)).

The counter is the reset mode. The impulse fires on the first output after reset, after a change
of `mode` and after each write of the `control` register, which re-arms it; zeros follow. The
`q` field of the `const` register sits above the `i` field, at bit 16 or at bit `data_width` when
the samples are wider.

`LiteDSPReplay`, in `litedsp/generation/source.py`, is an arbitrary waveform source. It loops over
a list of I/Q samples given at build time and held in a RAM, and marks the first and last sample
of each pass with `first` and `last`. It is not in the registry, so it has no datasheet; use it in
Python designs and tests.

In the code: `LiteDSPPatternSource` in `litedsp/generation/pattern.py`.

## Mixing {#gm-mixing}

The mixing family moves a signal in frequency. The complex mixer multiplies two I/Q streams; the
DDC and the DUC combine it with an NCO and a rate changer; the two channelizers split a wide band
into equally spaced channels. [Complex mixing](#pri-mixing) and [DDC and DUC](#pri-ddc) give the
theory.

### Mixer {#gm-mixer}

`LiteDSPMixer` multiplies its two inputs `sink_a` (the signal) and `sink_b` (the oscillator or a
second signal). The direction is a run-time control, not a build option:

| `mode` | Result | Use |
|--------|-------------------|------------------------------------------------------|
| 0 | `a * conj(b)` | Down-conversion: shift `a` down by the frequency of `b` |
| 1 | `a * b` | Up-conversion: shift `a` up by the frequency of `b` |

The two sinks are joined: a sample is taken from each in the same cycle, and only when both are
valid and the pipeline can advance. A block that feeds only one input therefore stalls the mixer,
which is what keeps the NCO aligned with the signal.

The datapath has two registered stages: the four products, then their sums or differences at full
precision (`2 * data_width + 1` bits). The result is rescaled by `shift` bits (`data_width - 1` by
default, the Q1.15 by Q1.15 case of [Rounding and saturation](#pri-rescale)) with round half up
and saturation. The latency is 2.

The `bypass` field selects the output: the mixed product (0), input A (1) or input B (2), each
delayed by the same two stages. The register map packs both controls in `control`:

| Field | Bits | Values |
|----------|-------|---------------------------------------------|
| `mode` | 0 | 0 down-conversion, 1 up-conversion |
| `bypass` | 9:8 | 0 mix, 1 pass input A, 2 pass input B |

`MixerDriver` in the host drivers sets both fields with a read-modify-write. The characterization
measures an image rejection of 117.56 dB with a LUT-exact NCO as the oscillator, measured on the
golden models.

In the code: `LiteDSPMixer` and the `MIXER_MODE_*` constants in `litedsp/mixing/mixer.py`.

### DDC {#gm-ddc}

The digital down-converter brings a band centred at the NCO frequency to baseband and lowers the
sample rate. It is a composite of three blocks: an NCO, a mixer fixed in down mode and a
decimator. The figure below shows the chain.

![DDC: the high-rate input is mixed down by the NCO, then decimated by a CIC or a FIR decimator;
the tuning word is the NCO phase increment register.](mix_ddc.svg)

The tuning word is the NCO increment, exposed as `nco_phase_inc`. Because the mixer computes
`a * conj(b)`, an increment of `+f` moves a tone at `+f` to 0 Hz: the DDC test in
`test/test_ddc_duc.py` sets the increment to the frequency of the input tone and checks that the
output is a constant. In the NCO formula, `fs` is the input sample rate.

The docstring of the class says to set `-f_tune`; the hardware and the test follow `+f_tune`
(fix pending, PR #13).

The decimator is `LiteDSPDecimator`, described in [Rate wrappers](#fr-rate-wrappers):

| Parameter | Default | Effect |
|------------------------|-------------|--------------------------------------------------|
| `decimation` | 8 | Rate reduction factor R |
| `method` | `"cic"` | `"cic"` (four-stage CIC) or `"fir"` (windowed-sinc FIR) |
| `fir_architecture` | `"classic"` | `"pipelined"` registers the FIR memory operands |
| `phase_bits` | 32 | Width of the NCO phase |

With `method="cic"` the only anti-alias filtering is the CIC response, with its droop. With
`method="fir"` the decimator runs a windowed-sinc low-pass of `8*R + 1` taps with a cutoff at 0.4
of the output rate. The FIR schedule, its timing option and the implementation results of the DDC
are in [FIR decimator](#fr-fir-decimator).

The `latency` attribute of the DDC is the sum of the 2 cycles of its mixer and the latency of its
decimator, 3 with the registry parameters, as the composite rule of [Latency](#arch-latency) asks.
The DUC, the channelizer, the parallel DDC and the derotator count their mixer the same way.

In the code: `LiteDSPDDC` in `litedsp/mixing/ddc.py`. The example `examples/ddc_chain.py` builds
the same chain from the individual blocks ([Getting started](#getting-started)).

### DUC {#gm-duc}

The digital up-converter is the transmit mirror of the DDC: an interpolator raises the rate of a
baseband stream, then the mixer, fixed in up mode, shifts it to the NCO frequency. An increment of
`+f` moves a baseband signal at 0 Hz to `+f` at the output rate, as `test/test_ddc_duc.py` checks.

The interpolator is `LiteDSPInterpolator`, with the same `method` and `fir_architecture`
parameters as the DDC. With `method="fir"` its low-pass has a gain of L to make up for the zeros
inserted between samples. The DUC registers are the NCO increment `nco_phase_inc` and the
configuration status of the interpolator. The schedule of the FIR interpolator and its
implementation results are in [FIR interpolator](#fr-fir-interpolator).

In the code: `LiteDSPDUC` in `litedsp/mixing/duc.py`; `examples/duc_chain.py` runs it.

### Channelizer {#gm-channelizer}

`LiteDSPChannelizer` splits a wide band into `n_channels` channels with one DDC per channel. A
split block copies the input to every DDC, and DDC `k` has its NCO preset to `k/n_channels` of the
input rate. Channel `k` is the band centred at that frequency, brought to baseband, on
`sources[k]`.

The decimation defaults to `n_channels` (critical sampling) and the method to `"fir"`. Every
channel is a full DDC, so the resources grow linearly with the number of channels: the simple and
flexible option for a few channels.

The NCOs are built without registers; their preset is the
reset value of `phase_inc`, which a design can change at elaboration. The bank passes its
`fir_architecture` option to every DDC: [FIR interpolator](#fr-fir-interpolator) records the
four-channel results of both choices.

In the code: `LiteDSPChannelizer` in `litedsp/mixing/channelizer.py`.

### PFB channelizer {#gm-pfb}

The polyphase filter bank (PFB) channelizer produces the same uniform channels with far fewer
resources: one prototype low-pass filter shared by all channels, split into M polyphase branches,
followed by an M-point DFT ([Polyphase filters](#pri-polyphase), [The FFT](#pri-fft)). One
multiply-accumulate unit computes all the branches and the transform in turn.

The figure below shows the datapath. A commutator writes consecutive input samples to the M branch
histories. Once per frame the shared MAC computes the M branch sums with the prototype taps, and
the transform turns them into one sample per channel.

![PFB channelizer: commutator, M branch histories, a shared MAC with the prototype ROM, an M-point
transform (direct DFT or radix-2 FFT) and the framed channel output.](mix_pfb.svg)

Channel `k` is the band centred at `+k/M` of the input rate (channels above M/2 are the negative
frequencies), brought to baseband and decimated by M. A tone exactly at `k/M` comes out as DC on
channel `k`. Each output frame is a burst of M samples, channel 0 to M-1, with `first` on channel 0
and `last` on channel M-1 ([Frames](#pri-framing)).

| Parameter | Default | Effect |
|------------------------|----------------|----------------------------------------------|
| `n_channels` | 4 | M, a power of two |
| `taps_per_channel` | 8 | T, taps per branch; the prototype has M times T taps |
| `coefficients` | windowed sinc | Prototype taps, Q1.15; default cutoff 0.4/M, unity DC gain |
| `architecture` | `"auto"` | `"classic"`, `"folded"`, `"fft"` or `"auto"` |
| `oversampling` | 1 | 1: M outputs per M inputs; 2: M outputs per M/2 inputs |

The arithmetic keeps full precision until the output. With W the sample width, the branch
accumulators hold `2*W + clog2(T) + 1` bits and the DFT accumulators add `W + clog2(M) + 1` bits.
The direct transforms round and saturate once, at the output. The FFT rounds each twiddle product
after every rank and has its own bit-exact golden model.

The architecture sets the schedule. The input is stalled while a frame computes, so the cycles per
frame bound the input rate at about `M * f_clk / cycles` samples per second:

| Architecture | Channels | Transform | Cycles per frame |
|--------------|----------|---------------------------|------------------------------------|
| `"classic"` | 2 to 8 | Direct DFT, one term a clock | H + M(T+1) + M(M+1) |
| `"folded"` | 2 to 8 | Direct DFT, two clocks a term | H + M(2T+1) + M(2M+1) |
| `"fft"` | 16 or more | Radix-2 DIF | H + M(2T+1) + 2M log2(M) + M |
| `"auto"` | any | Classic to 8, FFT from 16 | as selected |

H is the number of new input samples per frame, `M/oversampling`. The FFT path keeps a two-cycle
polyphase MAC and computes each butterfly in four clocks: register the memory read and the
difference, register the twiddle products, write the sum, write the difference. The direct DFT
grows as M squared, the FFT as M log M.

The elaborated blocks report their schedule in `cycles_per_frame`. This run, in the repository
root, prints it for three configurations with eight taps per channel:

```console
$ python3 -c "from litedsp.mixing.pfb_channelizer import LiteDSPPFBChannelizer as P
for m, a in ((4, 'classic'), (4, 'folded'), (16, 'fft')):
    print(m, a, P(n_channels=m, taps_per_channel=8, architecture=a).cycles_per_frame)"
4 classic 60
4 folded 108
16 fft 432
```

The 60 cycles of the registry configuration are also its `latency` attribute, in clock cycles.
For M=16 and T=8 the FFT frame takes 432 clocks, against 816 computed for the folded direct
schedule (the direct architectures are limited to M <= 8). The implementation results of every
PFB configuration are in [Mixing](#perf-mixing).

With `oversampling=2` each transform advances by M/2 new samples over overlapping histories, which
doubles the output rate. The DFT of a frame that starts half a frame later rotates the odd channels
by pi. The block corrects it with an alternating sign on the odd channels, so a tone at a channel
centre stays at DC; the FFT frame drops from 432 to 424 clocks in that mode.

The `config` status register returns the number of channels and the taps per branch. The
coefficients are fixed at build time: there is no reload interface. Tests cover M=16 and M=32,
the channel order, the framing, random stalls and Verilator co-simulation.

In the code: `LiteDSPPFBChannelizer` in `litedsp/mixing/pfb_channelizer.py`; its golden model is
`pfb_channelizer_model` in `test/models.py`.

## Correction {#gm-correction}

The correction family removes the impairments that an analog front end adds to a complex
baseband signal: a DC offset, an amplitude and phase mismatch between I and Q, and a carrier
frequency offset. The three blocks are in-line, keep the I/Q layout and have the `bypass` control
of [the block contract](#architecture).

### DC offset {#gm-dc-offset}

`LiteDSPDCOffset` estimates the mean of each axis with a leaky integrator and subtracts it. For
every accepted sample the estimate moves by `(x - mean) >> mu`, a first-order low-pass with its
pole at `1 - 2**-mu`. A larger `mu` (10 by default) gives a slower, finer estimate; the
accumulator carries `mu` fractional bits.

The output is `x` minus the floor of the estimate (an arithmetic shift), saturated to `data_width`,
with a latency of 1. The estimates are exposed as the `mean_i` and `mean_q` signals for monitoring,
but not as registers. The `bypass` control is a signal of the block; no register drives it.

For a fixed DC blocking filter without an exposed estimate, use the multiplier-free
`LiteDSPDCBlocker` of the filter family ([Small filters](#fr-small-filters)).

In the code: `LiteDSPDCOffset` in `litedsp/correction/dc_offset.py`.

### I/Q balance {#gm-iq-balance}

`LiteDSPIQBalance` corrects a gain and phase mismatch between I and Q with a 2 by 2 matrix: I
passes unchanged and Q is replaced by `(c1*I + c2*Q) >> coeff_frac`, rounded and saturated. The
reset values (`c1` = 0, `c2` = 1.0) pass the signal through.

The block also measures the mismatch, so that firmware can compute the coefficients and keep the
division and the square root out of the gateware. Over a window of `2**window_log2` accepted
samples it accumulates the sums of `I*I`, `Q*Q` and `I*Q` of the input, and latches them at the
end of each window into three status registers.

| Register | Access | Width | Meaning |
|----------|--------|-------|-------------------------------------------------|
| `c1` | rw | 16 | Cross term, Q2.14 with the defaults |
| `c2` | rw | 16 | Q gain, Q2.14 (reset 1.0, `0x4000`) |
| `acc_ii` | ro | 46 | Sum of I squared over the last window |
| `acc_qq` | ro | 46 | Sum of Q squared over the last window |
| `acc_iq` | ro | 46 | Sum of I times Q over the last window, signed |
| `bypass` | rw | 1 | Pass the input unchanged |

The widths are those of the defaults (`data_width=16`, `window_log2=14`); a 46-bit register takes
two words on a 32-bit register bus. One way to compute the coefficients is Gram-Schmidt
orthogonalization: remove from Q its projection on I, then scale the rest to the power of I.

```python
# ii, qq, iq: the three sums of one window (statistics of the uncorrected input).
a  = iq/ii                                  # Projection of Q on I.
c2 = (ii/(qq - a*iq))**0.5                  # Scale the orthogonal part to the power of I.
c1 = -a*c2
# Write round(c1 * 2**14) and round(c2 * 2**14) to the c1 and c2 registers.
```

The estimator sees the input of the block, before the correction, so the coefficients computed from
one window apply directly. The repository has no host driver for this block.

In the code: `LiteDSPIQBalance` in `litedsp/correction/iq_balance.py`.

### Derotator {#gm-derotator}

`LiteDSPDerotator` shifts a stream down in frequency by the NCO frequency. It is an NCO and a mixer
fixed in down mode, so the source is `sink * exp(-j 2 pi f n)`. Write a known carrier frequency
offset to `nco_phase_inc`, or drive `nco.phase_inc` from a carrier recovery loop. The NCO runs
free, so the latency is that of the mixer, 2 samples.

The blocks that estimate the offset are in the communications family ([Communications
blocks](#comm)).

In the code: `LiteDSPDerotator` in `litedsp/correction/cfo.py`.

## Parallel variants {#gm-parallel}

A converter that runs faster than the fabric clock delivers several samples per clock. The
parallel variants accept `n_samples` lanes per beat ([Sample rate, clock rate and
lanes](#pri-rates)) and produce, once the lanes are read in order, exactly the samples of the
serial block. They are not in the registry: they are used from Python, and the tests of
`test/test_parallel.py` compare each one with the serial golden model.

The parallel NCO advances its accumulator by `n_samples * phase_inc` per beat; lane `k` reads its
own ROM pair at `phase + (k + 1) * phase_inc`. The parallel mixer repeats the two-stage datapath
of the mixer on every lane, with the same rounding, the same latency of 2 and the `mode` field; it
has no bypass.

The parallel DDC chains the parallel NCO, the parallel mixer in down mode and the parallel CIC
decimator of [Parallel filters](#fr-parallel). Its `decimation` must be a multiple of
`n_samples`, so the output is at most one sample per clock: a serial I/Q stream that the serial
blocks take directly, with no parallel-to-serial adapter. The tuning
convention is that of the DDC. Its latency attribute adds the latencies of the mixer and the CIC.

A front end usually forms the lanes with `LiteDSPIQSerialToParallel` or a deserializer
([Stream utilities and host links](#stream-frontend)); [Parallel variants](#arch-parallel) lists
the files.

## Where to go next {#gm-next}

[Filters and rate change](#filters-rate) describes the decimators and interpolators inside the DDC
and DUC; [Level control and analysis](#level-analysis) measures the signals these blocks produce;
[Integration](#integration) puts a chain in a SoC.
