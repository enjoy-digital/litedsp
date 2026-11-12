# Sampled signals and fixed point {#dsp-primer}

This chapter explains the numbers that flow through LiteDSP to an FPGA engineer who has never
written signal processing code. It starts from sampling and complex baseband, gives the figures
used to judge a signal, then explains fixed-point arithmetic: formats, word growth, rounding and
saturation. It ends with the difference between sample rate and clock rate.

Each section gives the idea first, then the LiteDSP code that implements it. The next chapter,
[Streams, latency and rates](#stream-primer), explains how the samples move between blocks.

## Sampling and the Nyquist limit {#pri-sampling}

A converter measures an analog signal at regular instants and delivers one number per instant, a
*sample*. The number of samples per second is the *sample rate*, written fs. Between two samples
the digital side knows nothing: every block of LiteDSP works on this sequence of numbers only.

A sampled signal can only represent frequencies up to half the sample rate, the *Nyquist
frequency* fs/2. A tone above fs/2 is not lost: it folds back and appears at another frequency,
indistinguishable from a real tone there. This folding is *aliasing*. A tone at 0.7 fs, for
example, shows up at 0.3 fs.

Aliasing is why an analog filter sits in front of every converter, and why a digital design must
filter before it lowers the sample rate. [Decimation](#pri-decimation) explains the digital
case.

Because a block only sees samples, LiteDSP expresses frequencies as fractions of the sample
rate, the *normalized frequency*, in cycles per sample. For a real signal it runs from 0 to 0.5,
0.5 being fs/2. The filter design helpers of `litedsp/filter/design.py` take their cutoffs in
this unit, and a block never needs to know the sample rate in hertz.

## Real and complex baseband {#pri-iq}

A real signal has a spectrum that is symmetric around 0 Hz: a cosine at f0 is the sum of two complex
exponentials, one at +f0 and one at -f0.

A receiver that mixes a radio band down to 0 Hz with a single real multiplier cannot tell what was
above the carrier from what was below: both fold onto the same frequencies.

The answer is to carry two samples per instant: the *in-phase* part I and the *quadrature* part
Q, read together as the complex number I + jQ. A complex signal has no symmetry constraint, so it
can hold a tone at +f0 without its mirror at -f0, as the figure below shows.

![Spectrum of a real tone and of a complex tone. The real signal always carries the mirror line
at -f0; the complex signal I + jQ holds a single line at +f0, so positive and negative
frequencies are distinct.](pri_iq.svg)

A complex stream sampled at fs covers the band from -fs/2 to +fs/2: a total bandwidth of fs,
twice what a real stream at the same rate covers. This is *complex baseband*, the form most RF
transceivers deliver, the Analog Devices AD9361 among them.

Most LiteDSP blocks work on complex samples. Their stream carries two signed fields, `i` and
`q`, defined by `iq_layout` in `litedsp/common.py`. Real streams carry a single signed `data`
field (`real_layout`). The Hilbert transformer turns a real stream into a complex one, see
[Hilbert transformer](#pri-hilbert).

## Measuring a signal {#pri-metrics}

A handful of figures describe how clean a digital signal is. The table below lists the ones this
manual uses. All are ratios expressed in decibels: 20 log10 of an amplitude ratio, or 10 log10
of a power ratio.

| Figure | Meaning |
|---------|----------------------------------------------------------------------------------|
| dBFS | Level relative to full scale: 0 dBFS is the largest sine the format can hold |
| SNR | Signal-to-noise ratio: signal power over noise power |
| SINAD | Signal over noise and distortion: noise plus harmonics and spurs |
| SFDR | Spurious-free dynamic range: signal over the largest spur |
| ENOB | Effective number of bits: (SINAD - 1.76) / 6.02 |

An ideal N-bit quantizer driven by a full-scale sine reaches an SNR of 6.02 N + 1.76 dB: each bit
adds about 6 dB. A 16-bit sample is therefore limited to about 98 dB.

A block that loses one bit of precision costs 6 dB. ENOB inverts this formula: it is the number
of bits an ideal quantizer would need to reach the measured SINAD.

LiteDSP measures these figures on the golden models of its blocks with the characterization
scripts of `char/`: `char/metrics.py` holds `sfdr_db`, `sinad_db`, `enob_bits`,
`noise_floor_dbfs` and their companions. [Performance](#performance) gives the recorded values.

## Fixed-point numbers {#pri-qformat}

An FPGA multiplies integers cheaply, and floating point costs much more logic. LiteDSP therefore
uses *fixed point*: each sample is a signed integer with an implied binary point. The format
Qm.n has m integer bits, the sign bit included, and n fractional bits, for a total width of
m + n bits. The figure below shows three formats.

![Bit fields of three signed fixed-point formats. S is the sign bit and I an integer bit. Q1.15
is the default sample format, Q2.14 the format of a gain mantissa, and Q2.30 the full product of
two Q1.15 numbers.](pri_qformat.svg)

The value of a Qm.n word is its two's-complement integer divided by 2^n. Its range runs from
-2^(m-1) to 2^(m-1) - 2^-n, in steps of 2^-n, the *LSB*. The table below gives the formats met in
LiteDSP.

| Format | Width | Range | Use in LiteDSP |
|--------|-------|---------------------|--------------------------------------------------|
| Q1.15 | 16 | -1.0 to 1.0 - 2^-15 | Default sample (`data_width=16`) |
| Q2.14 | 16 | -2.0 to 2.0 - 2^-14 | Gain mantissa of `LiteDSPGain` |
| Q2.30 | 32 | -2.0 to 2.0 - 2^-30 | Product of two Q1.15 numbers |
| Q4.28 | 32 | -8.0 to 8.0 - 2^-28 | Coefficients of `LiteDSPAudioEQ` |

Coefficients do not always use a sample format. The IIR biquad, for example, takes integer
coefficients with 14 fractional bits (`frac_bits=14`) and as many integer bits as their values
need. The format is a convention between the design helper and the block, stated in each
block's documentation.

The default Q1.15 format spans -1.0 to just under +1.0. Its asymmetry is the one of two's
complement: -1.0 exists, +1.0 does not. Coefficient tables built for Q1.15, such as the NCO
lookup tables, use 2^15 - 1 as their full scale so that +1.0 never has to be represented.

## Word growth {#pri-growth}

Arithmetic makes words grow. The product of a Qa.b number by a Qc.d number is exactly a
Q(a+c).(b+d) number: two Q1.15 samples give a Q2.30 product of 32 bits. The extra integer bit is
only needed for one case, -1.0 times -1.0, whose result +1.0 does not fit Q1.30.

A sum also grows. Adding K numbers of the same format can need up to ceil(log2 K) more integer
bits. A 64-tap FIR filter therefore accumulates its 32-bit products on at least 38 bits. LiteDSP
sizes these intermediate words explicitly: `LiteDSPFIRFilter` computes its accumulator width from
the product width and the number of products, with one guard bit on top.

Some structures grow much more. A CIC decimator of rate R with N stages and a differential delay M,
usually 1, has a gain of (R M)^N, and its registers need N log2(R M) more bits than the input; see
[CIC filters](#pri-cic). As a rule, a LiteDSP block keeps full precision inside, then brings the
result back to the sample width once, at its output.

## Rounding and saturation {#pri-rescale}

Bringing a wide result back to the sample width removes low bits and may remove high bits. Each
step has a right and a wrong way, and the wrong way is the cheapest. The figure below shows the
rescale of a Q2.30 product to Q1.15.

![Rescaling a product back to the sample format. Adding half an output LSB then shifting right
by 15 rounds the value; the clamp then saturates it to the 16-bit range. `scaled()` also returns
an overflow flag, set when the clamp had to clip.](pri_rescale.svg)

Dropping low bits by a plain shift *truncates*: it rounds toward minus infinity. The error is always
negative, between 0 and -1 LSB, so truncation adds a DC offset of half an LSB.

Its error power, offset included, is four times the one of rounding: about 6 dB more noise. Adding
half an LSB before the shift *rounds* to the nearest value instead, with no measurable bias.

Dropping high bits keeps only the low part of a value that no longer fits. In two's complement
this *wraps*: a value just above +1.0 becomes a value near -1.0, and a loud signal turns into
noise. *Saturation* clamps the value to the largest or smallest representable number instead:
the waveform is clipped, but its sign and shape survive.

One structure relies on wrapping on purpose: the CIC filter, whose integrators overflow and
whose combs undo the overflow exactly. [CIC filters](#pri-cic) explains why this works.
Everywhere else, LiteDSP rounds then saturates.

## Fixed point in LiteDSP {#pri-fixed-point}

LiteDSP samples are signed two's-complement Qm.n numbers. The default sample format is Q1.15, 16
bits with a range of -1.0 to just under +1.0, which matches typical RF data paths. The helpers live
in `litedsp/common.py`.

Their NumPy twins, used by the golden models, live in `test/common.py` (`np_rounded`,
`np_saturated`, `np_scaled`) and give identical results, so that a simulation can be checked bit for
bit.

### The format descriptor {#pri-qmn}

`Qmn(m, n)` describes a format. The table below lists what it provides; `Q15 = Qmn(1, 15)` is the
default format.

| Member | Value |
|----------------|--------------------------------------------------------------------|
| `width` | Total width, m + n |
| `shape` | Migen signed shape `(width, True)` |
| `scale` | LSBs per integer unit, 2^n |
| `to_float()` | Raw integer to float |
| `from_float()` | Float to raw integer, rounded and clamped to the range |

### The rescaling rule {#pri-rescale-rule}

After a multiply or an accumulation, a result is wider than a sample and must be brought back to
the target width. The rule is to always round then saturate, never to slice, truncate or let a
value wrap. The helpers below return Migen expressions, used inside `self.comb` or `self.sync`.

| Helper | Effect |
|---------------|-----------------------------------------------------------------------------|
| `rounded` | Arithmetic shift right by `shift`, rounding half up: floor(value / 2^shift + 0.5) |
| `saturated` | Clamp to the signed `out_width` range |
| `scaled` | `rounded` then `saturated`; returns `(result, overflow)` |
| `overflow` | 1 when the signed value does not fit `out_width` bits |
| `clamped` | Clamp to the unsigned range 0 to 2^out_width - 1 (pixel codes) |

The table below gives the typical shifts. A sample times a coefficient, both Q1.15, gives a
Q2.30 product that a shift of `data_width - 1`, 15, brings back to Q1.15. A sample times a Q2.14
gain mantissa gives a Q3.29 product that a shift of 14, plus the extra shift of the gain block,
brings back.

| Operation | Operand formats | Shift to return to Qm.n |
|------------------------|--------------------------|---------------------------------------|
| Sample by coefficient | Q1.15 by Q1.15 to Q2.30 | `data_width - 1` (15) |
| Sample by gain | Q1.15 by Q2.14 to Q3.29 | `gain_frac` (14) plus the extra shift |

A few width traps remain between Migen simulation and the Verilog output, such as the signed
constants of the `overflow` test; [Debugging](#debugging) covers them.

## Sample rate, clock rate and lanes {#pri-rates}

The *sample rate* is the rate of the signal; the *clock rate* is the rate of the logic that
processes it. They are independent. A LiteDSP block processes at most one sample per clock
cycle and per stream, and the stream handshake tells it when a sample is present (see [The
valid/ready handshake](#pri-handshake)).

When the sample rate is below the clock rate, the stream simply has idle cycles. A 10 MSPS complex
stream processed at 100 MHz carries a sample on one cycle in ten.

Several blocks use these idle cycles to save logic, with a *folded* or *MAC* architecture that
reuses one multiplier over several cycles. They advertise how often they accept a sample, as the
table below shows.

| Block | Option | Accepts at most |
|------------------------------|--------------|--------------------------------------------|
| `LiteDSPIIRBiquad` | `"folded"` | One sample every 3 cycles (`sample_interval`) |
| `LiteDSPFFT` | `"folded"` | One sample every 2 cycles (`sample_interval`) |
| `LiteDSPGoertzel` | `"folded"` | One sample every 2 cycles (`sample_interval`) |
| `LiteDSPFIRFilter` | `"mac"` | One sample every `cycles_per_sample` cycles |
| `LiteDSPFIRDecimator` | default | One output every `cycles_per_output` cycles |

The option is the `architecture` argument of the block. The default architecture of the first
four blocks accepts one sample per cycle.

When the sample rate is above the clock rate, one sample per cycle is not enough. The *parallel*
variants then carry several samples per beat, each one a *lane*.

The `n_samples` argument of `real_layout` and `iq_layout` sets the number of lanes. The lanes are
concatenated in each field, lane 0 in the low bits and holding the first, oldest sample;
`real_lanes` and `iq_lanes` slice them back.

A parallel variant produces, lane after lane, the same samples as its serial block: it is bit
identical. [Parallel variants](#arch-parallel) lists them, with the adapters between a serial and
a lane stream.

Where to go next: [Streams, latency and rates](#stream-primer) for the stream handshake and rate
change, [Digital filters](#filter-primer) for filters.
