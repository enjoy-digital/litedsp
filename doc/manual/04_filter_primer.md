# Digital filters {#filter-primer}

This chapter explains digital filters to an FPGA engineer who has not designed one. It starts with
what a filter does and how its response is described, then covers the FIR filter, its design and its
multirate forms: polyphase, half-band and CIC.

It continues with recursive (IIR) filters and ends with a few special filters: moving average, DC
blocker, Hilbert transformer and fractional delay.

Each section ends with the LiteDSP blocks and helpers that implement the idea. [Filters and rate
change](#filters-rate) then describes those blocks in detail.

## What a filter does {#pri-filter-basics}

A digital filter computes each output sample from the newest input, past inputs and, for some
filters, past outputs.

The filters of this chapter are *linear* and *time-invariant*: doubling the input doubles the
output, and delaying the input delays the output. Such a filter is fully described by its *impulse
response*, the output it gives for a single sample of value 1.

The same filter can be described in frequency. Its *frequency response* tells, for each
frequency, by how much a sine is scaled and shifted in phase. A low-pass filter keeps the low
frequencies, its *passband*, and removes the high ones, its *stopband*; between them lies the
*transition band*. The table below gives the figures that specify a filter.

| Figure | Meaning |
|-------------------------|----------------------------------------------------------------|
| Cutoff | Edge of the passband, in normalized frequency (0 to 0.5) |
| Passband ripple | Peak-to-peak gain variation inside the passband, in dB |
| Stopband attenuation | Smallest rejection inside the stopband, in dB |
| Transition width | Distance between passband edge and stopband edge |
| Group delay | Delay of the signal envelope through the filter, in samples |

A sharper filter, with a narrow transition band or a deep stopband, costs more: more taps for a
FIR filter, a higher order for an IIR filter. In LiteDSP all frequencies are normalized to the
sample rate the filter runs at, as [Sampling and the Nyquist limit](#pri-sampling) explains.

## FIR filters {#pri-fir}

A *finite impulse response* (FIR) filter computes each output as a weighted sum of the last N
inputs: y[n] = c0 x[n] + c1 x[n-1] + c2 x[n-2] and so on, up to c(N-1) x[n-N+1].

The weights c are the *coefficients*, or *taps*, and N is the number of taps. The impulse response
is the list of taps itself, so it ends after N samples. The figure below shows a three-tap filter.

![A three-tap FIR filter. The delay line holds the last samples, each tap multiplies one of them
by its coefficient, an adder tree sums the products, and the sum is rounded and saturated to the
sample width.](pri_fir.svg)

A FIR filter has no feedback, so it is always stable, and its coefficients are used as given.
Its cost is one multiplication per tap and per output sample. At one sample per clock, an N-tap
filter needs N multipliers, usually N DSP blocks of the FPGA.

The gain of a FIR filter at 0 Hz, its *DC gain*, is the sum of its taps. The LiteDSP design
helpers normalize the taps to a DC gain of 1.0 and quantize them to Q1.15, the sample format.
The filter then rescales its accumulator by `data_width - 1` bits, as [Fixed point in
LiteDSP](#pri-fixed-point) explains.

In LiteDSP, `LiteDSPFIRFilter` is the real FIR filter and `LiteDSPFIRFilterComplex` its complex
version, with taps loaded through registers; [FIR filters](#fr-fir) describes their architectures
and coefficient ports.

## Linear phase and symmetry {#pri-linear-phase}

A filter delays each frequency by some amount. If the delay differs between frequencies, the
shape of a wideband signal changes as it passes: this is phase distortion. A FIR filter whose
taps are *symmetric*, c[k] = c[N-1-k], delays every frequency by the same (N-1)/2 samples. It has
*linear phase*, and its group delay is constant.

Linear phase is why most FIR filters of a communication chain are symmetric. Symmetry also saves
multipliers: the two samples that share a coefficient can be added first, then multiplied once.
A symmetric N-tap filter needs about N/2 multipliers.

| Type | Length | Symmetry | Typical use |
|------|--------|----------------|------------------------------------------------------|
| I | Odd | Symmetric | Low-pass, band-pass, half-band |
| II | Even | Symmetric | Low-pass (zero response at fs/2) |
| III | Odd | Antisymmetric | Hilbert transformer, differentiator |

The LiteDSP FIR filters fold the tap pairs with `symmetric=True`; the caller must provide
symmetric taps.

## Designing FIR taps {#pri-fir-design}

The ideal low-pass filter has a rectangular frequency response; its impulse response is a sinc
function, infinitely long. The *window method* keeps N samples of that sinc and multiplies them
by a smooth *window* that tapers to zero at both ends. The window sets the trade-off: a wider
main lobe gives a wider transition band but a deeper stopband.

The *Parks-McClellan* method, also called *Remez exchange*, designs an optimal filter instead. It
spreads the error evenly over the passband and the stopband, an *equiripple* response, and
reaches a given specification with fewer taps than a window.

LiteDSP designs its taps in Python, at build or test time, with `litedsp/filter/design.py`: NumPy
only, integer taps quantized to the block format, windowed sinc, Kaiser and Parks-McClellan
designers. [Design helpers](#fr-design) lists them.

Quantization changes the response. Rounding each tap to 16 bits adds a small error to the
frequency response, which can limit the stopband of a deep filter. The helpers compute the
response of the quantized taps actually used by the hardware, with its passband ripple, stopband
attenuation and DC gain.

## Polyphase filters {#pri-polyphase}

A decimator by R keeps one filter output out of R, so computing the other R - 1 is wasted. The
*polyphase* form avoids it.

Split the taps into R sub-filters, sub-filter p taking taps p, p + R, p + 2R and so on. Each output
is the sum of the R sub-filters, each fed with every R-th input sample, as the figure below shows.

![A polyphase decimator. The commutator deals the input samples to R sub-filters; each sub-filter
holds every R-th tap, c[p::R], and runs at the output rate. Their sum is one output
sample.](pri_polyphase.svg)

All the sub-filters run at the output rate, so the decimator does N multiplications per output
instead of N per input. The interpolator is the mirror: each input sample feeds every
sub-filter, and sub-filter p computes output phase p, so no multiplication is spent on the
inserted zeros.

The LiteDSP polyphase decimator and interpolator go one step further: one multiplier per I and
Q, time-shared over the taps ([Polyphase FIR](#fr-polyphase)).

## Half-band filters {#pri-halfband}

A *half-band* filter is a low-pass filter with its cutoff at a quarter of the sample rate, 0.25 in
normalized frequency.

Its response is symmetric about that point, and this symmetry makes every other tap exactly zero,
except the centre tap, which is 0.5. A half-band filter of N taps therefore needs only about N/4
multiplications per output with symmetric folding.

A half-band filter is the natural filter for a rate change by 2: the band it keeps is exactly the
band a factor of 2 can hold. Several half-band stages in a row decimate by 4, 8 or 16 cheaply.

The LiteDSP half-band blocks skip the zero taps in their multiply-accumulate schedule
([Half-band filters](#fr-halfband)).

## CIC filters {#pri-cic}

A *cascaded integrator-comb* (CIC) filter changes the rate by large factors without any
multiplier. It chains N *integrators*, each a running sum y[n] = y[n-1] + x[n], the rate change,
and N *combs*, each a difference y[n] = x[n] - x[n-M]. M is the *differential delay*, usually 1.
The figure below shows the decimator and the interpolator.

![CIC decimator and interpolator. The decimator runs N integrators at the input rate, keeps one
sample out of R, then runs N combs at the output rate. The interpolator mirrors it: combs, zero
insertion, integrators. Both rescale the result by the CIC gain.](pri_cic.svg)

The cascade is equivalent to N moving averages of R M samples. Its response has the shape of a
sinc raised to the power N, with nulls exactly on the frequencies that would alias onto 0 Hz.
Its gain at 0 Hz is (R M)^N: a decimator by 64 with 4 stages has a gain of 2^24.

The integrators overflow: a running sum of a constant input grows forever. This does not matter. In
two's complement, the final result is correct modulo 2^W, and the combs compute exact differences of
the wrapped values.

As long as the registers have N log2(R M) bits more than the input, enough for the true output,
wrapping cancels out. This is the Hogenauer property, and the one place where LiteDSP relies on
wrap-around.

A CIC filter has a drooping passband: its sinc response already falls inside the band it keeps.
A short FIR filter after it, at the low rate, corrects the droop with an inverse-sinc response.
This *compensation filter* usually also does the final band shaping and a last decimation by 2.

The interpolator has a gain of (R M)^N / R, since zero insertion divides the level by R.

In LiteDSP, the CIC decimator and interpolator size their registers for this growth and rescale
the output; [CIC filters](#fr-cic) gives their parameters, variants and the compensation helper.

## IIR filters and biquads {#pri-iir}

An *infinite impulse response* (IIR) filter also feeds back its past outputs: y[n] = b0 x[n] + b1
x[n-1] + b2 x[n-2] - a1 y[n-1] - a2 y[n-2]. The feedback makes the impulse response last forever,
decaying.

An IIR filter reaches a sharp response with far fewer multiplications than a FIR filter, at the cost
of a non-linear phase and of stability concerns.

The feedback coefficients place the *poles* of the filter. A filter is stable only if every pole
lies inside the unit circle; a pole close to the circle gives a sharp resonance, and quantizing
its coefficients can move it outside. High-order IIR filters are therefore built as a cascade of
second-order sections, *biquads*, each with two poles and well-conditioned coefficients.

A biquad can be computed in several equivalent forms. The *transposed direct form II* (DF2T)
needs only two state registers. The output is b0 x plus the first state; each state register
holds the feed-forward and feedback products of the newest sample plus the next state, as the
figure below shows.

![A transposed direct form II biquad. Tap 0 adds b0 x to the state s1 to give the output; tap 1
computes the next s1 from b1 x, -a1 y and s2; tap 2 computes the next s2 from b2 x and -a2 y. The
rounded output y feeds back into taps 1 and 2.](pri_biquad.svg)

Rounding inside a feedback loop is delicate. The rounding error recirculates, and with poles
close to the unit circle it is amplified. *Error feedback* subtracts the previous rounding error
from the next sum, shaping the rounding noise away from low frequencies; it serves low-frequency
audio sections well.

In LiteDSP, `LiteDSPIIRBiquad` is one DF2T section on I and Q with Q2.14 coefficients, and the
design helpers produce Butterworth and Chebyshev sections ([IIR biquads](#fr-iir)). The audio
equalizer uses the *direct form I* with error feedback ([Audio](#audio)).

## Moving average and DC blocker {#pri-small-filters}

The *moving average* outputs the mean of the last L samples. Instead of L additions per sample,
it keeps a running sum: add the new sample, subtract the one L samples old. It is a one-stage CIC
without rate change. With L a power of two, the division is a shift.

`LiteDSPMovingAverage` averages 2^`length_log2` samples on I and Q.

A *DC blocker* removes the constant part of a signal, such as the offset of a converter, and keeps
the rest.

The classic form is a first-order high-pass filter, y[n] = x[n] - x[n-1] + p y[n-1], with a pole p
just below 1. The closer p is to 1, the narrower the notch at 0 Hz and the slower the filter
settles.

`LiteDSPDCBlocker` places the pole at 1 - 2^-`pole_shift`, so the multiplication by p is a
shift and a subtraction. [Small filters](#fr-small-filters) describes both blocks, with the notch,
comb and all-pass filters.

## Hilbert transformer {#pri-hilbert}

A *Hilbert transformer* shifts the phase of every positive frequency by -90 degrees. Feed a real
signal to one, take its output as Q and a delayed copy of the input as I: the result I + jQ is
the *analytic signal*, a complex signal with the negative frequencies removed (see [Real and
complex baseband](#pri-iq)).

The ideal Hilbert transformer has an infinite impulse response; a practical one is an
antisymmetric FIR filter of odd length, Type III, whose taps at an even distance from the
centre, including the centre tap, are zero. Its delay is (N-1)/2
samples, so the I path must be delayed by the same amount to stay aligned.

`LiteDSPHilbert` builds both paths, a pure delay on I and the Hilbert filter on Q, from a real
stream; [Small filters](#fr-small-filters) gives its parameters.

## Fractional delay and the Farrow structure {#pri-farrow}

Sometimes a sample is needed between two input samples, at a fraction mu of the sample period:
to delay a signal by less than a sample, or to resample at an arbitrary ratio. Fitting a
polynomial through a few neighbouring samples gives that value. A cubic polynomial through four
samples is the usual choice.

The *Farrow structure* writes the interpolated value as a polynomial in mu whose coefficients are
fixed FIR combinations of the four samples. It evaluates the polynomial by Horner's method, so mu
can change on every sample without recomputing any coefficient.

`LiteDSPFarrowInterpolator` is a cubic Farrow interpolator with the Catmull-Rom polynomial. Its
control `mu` is the fractional position, an unsigned 15-bit fraction in [0, 1)
([Farrow interpolator](#fr-farrow)).

Where to go next: [Filters and rate change](#filters-rate) for the filter blocks in detail,
[Oscillators, mixers and the FFT](#spectral-primer) for the spectral blocks.
