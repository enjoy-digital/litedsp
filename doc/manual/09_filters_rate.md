# Filters and rate change {#filters-rate}

This chapter describes the filter family (`litedsp/filter/`) and the rate family (`litedsp/rate/`):
the FIR filters and their coefficient interfaces, the polyphase decimators and interpolators, the
half-band and CIC filters, the IIR and small filters, the resamplers, the LMS equalizer, the rate
wrappers, the resampler farm, the parallel filters and the design helpers. Read it to choose a
filter for a rate, a response and a resource budget, and to load its coefficients.

The theory is in [Digital filters](#filter-primer) (FIR, polyphase, half-band, CIC, biquads, Farrow)
and in [Streams, latency and rates](#stream-primer) (decimation, interpolation, resampling). Every
block follows [the block contract](#architecture). The maturity of the families is in the
[status table](#intro-status).

## At a glance {#fr-glance}

| Block | Class | Rate | Latency |
|----------------------|----------------------------------------|------|-------|
| FIR (real) | `LiteDSPFIRFilter` | 1 | 3 |
| FIR (complex) | `LiteDSPFIRFilterComplex` | 1 | 3 |
| FIR decimator | `LiteDSPFIRDecimator` | 1/R | 33 |
| FIR interpolator | `LiteDSPFIRInterpolator` | L | 32 |
| Half-band decimator | `LiteDSPHalfbandDecimator` | 1/2 | 24 |
| Half-band interpolator | `LiteDSPHalfbandInterpolator` | 2 | 23 |
| CIC decimator | `LiteDSPCICDecimator` | 1/R | 1 |
| CIC interpolator | `LiteDSPCICInterpolator` | R | 1 |
| Bitstream decimator | `LiteDSPBitstreamDecimator` | 1/R | 1 |
| IIR biquad | `LiteDSPIIRBiquad` | 1 | 2 |
| DC blocker | `LiteDSPDCBlocker` | 1 | 1 |
| Moving average | `LiteDSPMovingAverage` | 1 | 1 |
| Notch | `LiteDSPNotch` | 1 | 1 |
| Comb filter | `LiteDSPCombFilter` | 1 | 1 |
| Allpass | `LiteDSPAllpass` | 1 | 1 |
| Hilbert | `LiteDSPHilbert` | 1 | 3 |
| Farrow interpolator | `LiteDSPFarrowInterpolator` | 1 | 7 |
| Arbitrary resampler | `LiteDSPArbResampler` | any | none |
| Rational resampler | `LiteDSPRationalResampler` | L/M | none |
| Pulse shaper (RRC) | `LiteDSPPulseShaper` | sps | 33 |
| LMS equalizer | `LiteDSPLMSEqualizer` | 1 | 1 |
| Decimator | `LiteDSPDecimator` | 1/R | 1 |
| Interpolator | `LiteDSPInterpolator` | R | 1 |
| Downsampler | `LiteDSPDownsampler` | 1/n | 1 |
| Upsampler | `LiteDSPUpsampler` | n | 1 |
| Resampler farm | `LiteDSPResamplerFarm` | 1/R | 32 |

Rate is the output rate over the input rate; latency is in samples with the registry parameters,
as in the catalogue, and "none" means data dependent. Each section says how the block takes its
coefficients: build-time parameters, registers or a reload port. The registers of every block are in
[Filtering](#reg-filter) and [Rate conversion](#reg-rate); the datasheets are in the
[block catalogue](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md).

## Choosing a filter {#fr-choosing}

Most choices follow from three questions: does the rate change, how sharp must the response be,
and how many clocks are there per sample. The table maps common needs to blocks.

| Need | Block | Why |
|-------------------------------------------|-------------------------------|---------------------------------------|
| Sharp low-pass, one sample per clock | FIR, `"classic"` or `"pipelined"` | One multiplier per tap, full rate |
| Same, sample rate well below the clock | FIR, `"mac"` | A few multipliers, time-shared |
| Decimate by R with a clean passband | FIR decimator | One MAC per axis, R + N + 1 clocks per output |
| Decimate by 2 | Half-band decimator | Half the taps are zero and skipped |
| Decimate by a large R, no multiplier | CIC decimator | Adders only; droop to compensate |
| Many channels, same rate | Resampler farm | One MAC engine for all channels |
| Resonant or narrow response, few taps | IIR biquad, notch | Feedback; 5 coefficients per section |
| Remove DC | DC blocker | No multiplier |
| Non-integer rate ratio | Rational or arbitrary resampler | Polyphase L/M, or Farrow |

Two LiteDSP conventions run through all the blocks below. Samples are signed Q1.15 by default
(Q1.n for `data_width` = n + 1), and so are the FIR coefficients; the recursive filters use Q2.14
coefficients, as each section says. Every output is rescaled once with round half up and
saturation ([Rounding and saturation](#pri-rescale)). The filters that compute serially
publish their schedule in a `cycles_per_output` or `cycles_per_sample` attribute.

## FIR filters {#fr-fir}

### Datapath {#fr-fir-datapath}

`LiteDSPFIRFilter` computes `y[k] = sum of coeffs[t] * x[k-t]` over `n_taps` taps, one sample per
clock. The figure below shows its datapath in the default architecture.

![Real FIR datapath: shift register, optional symmetric fold, registered products, adder tree,
round and saturate, output.](flt_fir_pipe.svg)

The shift register holds the last `n_taps` samples and advances only when a sample is accepted, so
idle cycles never enter the convolution history. Every product is registered. A balanced adder
tree sums the products at full precision, `2 * data_width + ceil(log2(products)) + 1` bits; the
sum is rescaled by `shift` bits (`data_width - 1` by default) and registered at the output. The
latency of the default architecture is 3.

With `symmetric=True` the filter adds each pair of mirrored samples before the multiplier, which
halves the number of multipliers of a linear-phase filter ([Linear phase and
symmetry](#pri-linear-phase)). The coefficients must then be symmetric; the block does not check
them.

The real FIR takes its coefficients from `coeffs`, an array of signals that the enclosing design
drives. It has the delay-matched `bypass` control of [the block contract](#architecture), as a
signal. The complex FIR below adds the coefficient registers.

### Architectures {#fr-fir-arch}

The `architecture` parameter trades multipliers, latency and clock rate:

| Architecture | Multipliers | Throughput | Latency |
|-------------------|-----------------------|------------------------|-----------------------------|
| `"classic"` | One per product | One sample per clock | 3 |
| `"pipelined"` | One per product | One sample per clock | 3 + one per adder-tree level |
| `"mac"` | `n_macs` (4 by default) | One sample per scan | Schedule dependent |

The pipelined architecture registers every level of the adder tree, at the final width, so the
arithmetic is unchanged. Without these registers a vendor tool can flatten a runtime-coefficient
FIR into one long DSP cascade.

The MAC architecture computes the convolution serially. Each of the `n_macs` units owns a
contiguous chunk of taps and scans it, with the operand multiplexer, the product and the
accumulation each on its own clock; a pairwise tree then adds the partial sums, one level per
clock.

It suits a decimated stream, such as the output of a CIC, where a new sample arrives at
most every `cycles_per_sample` clocks; a faster input is backpressured. Its output is
sample-exact with the classic one, and it does not support the symmetric fold.

The elaborated filter reports these numbers. This run, in the repository root, prints the latency
of the two parallel architectures and the cycles per sample of the MAC one, for 32 taps:

```console
$ python3 -c "
from litedsp.filter.fir import LiteDSPFIRFilter
for a in ('classic', 'pipelined', 'mac'):
    f = LiteDSPFIRFilter(n_taps=32, architecture=a)
    print(a, f.latency if a != 'mac' else f.cycles_per_sample)"
classic 3
pipelined 8
mac 14
```

The pipelined filter adds five levels for 32 products. The MAC filter scans 8 taps per unit, plus
two pipeline clocks, two tree levels, and the accept and present cycles.

### Complex FIR and coefficient loading {#fr-fir-coeffs}

`LiteDSPFIRFilterComplex` runs two real FIRs, one on I and one on Q, with shared coefficients. It
accepts the same `symmetric`, `architecture` and `n_macs` parameters. Its coefficients live in
`LiteDSPFIRCoefficients`: one register per tap, `coeff_<t>`, which appear as `coeffs_coeff_<t>`
in the bank of the block. The default is a unit impulse (tap 0 at full scale), a transparent
filter; `coefficients` preloads a design.

The complex FIR has its own `bypass` register. Bypassed, it connects its input straight to its
output with no latency, so switching `bypass` while samples are in flight can reorder beats: switch
it while the stream is idle ([Known issues](#intro-known-issues)).

A filter bank with many taps per filter makes one register per tap expensive: the register map
grows and the bus write decode can become the critical path. `LiteDSPFIRCoefficientsPort` holds
the same coefficients behind two registers:

| Register | Access | Meaning |
|------------|--------|-------------------------------------------------------------|
| `index` | rw | Tap to write; increments after each `value` write |
| `value` | rw | Writes the coefficient at `index` |
| `readback` | ro | Coefficient at `index`, registered; with `with_readback=True` |

To load a filter, write `index` = 0 and then the taps in order. Over a bus that does not
acknowledge writes, such as Etherbone over UDP, one lost `value` write shifts every later tap by
one without any error; the readback lets the host verify a load tap by tap. No registry block uses
the port: a design instantiates it and drives the `coeffs` of its FIRs from its `values`.

The host side is `FIRDriver` in `litedsp/software/drivers.py`. It finds the `coeff_<k>` registers
under its prefix, so for a complex FIR named `fir` the prefix is `fir_coeffs`.

```python
fir = FIRDriver(bus, "fir_coeffs")
fir.set_lowpass(0.125)              # Windowed sinc, cutoff fs/8, all hardware taps.
fir.set_remez(0.10, 0.15)           # Equiripple: pass to 0.10 fs, stop from 0.15 fs.
fir.load(taps)                      # Integers, or floats scaled to Q1.15.
```

`load()` scales a float by `2**(data_width - 1)` and saturates it to Q1.(N-1): 1.0 gives the
largest code, 32767 in 16 bits. The design functions return integers.

The characterization of a 63-tap windowed-sinc low-pass (`firwin_lowpass(63, 0.2)`, Q1.15 taps)
records a passband ripple of 0.019 dB and a stopband attenuation of 54.973 dB, measured on the
golden models.

In the code: `litedsp/filter/fir.py` (`LiteDSPFIRFilter`, `LiteDSPFIRFilterComplex`,
`LiteDSPFIRCoefficients`, `LiteDSPFIRCoefficientsPort`).

## Polyphase decimator and interpolator {#fr-polyphase}

When the fabric clock is faster than the sample rate, a filter does not need one multiplier per
tap. The polyphase FIRs of `litedsp/filter/fir_poly.py` use a single time-shared
multiply-accumulate unit per axis, two multipliers for a complex stream, and spend clocks instead
([Polyphase filters](#pri-polyphase)). Their throughput is bounded by the length of the MAC scan.

### FIR decimator {#fr-fir-decimator}

`LiteDSPFIRDecimator` collects R input samples, then computes one output from the N taps over the
sample history: `y[m] = sum of c[t] * x[mR - t]`. Samples and coefficients are in memories; a state
machine loads the window, scans the taps, drains the pipeline and presents the output, stalling the
input meanwhile.

| Parameter | Default | Effect |
|------------------|--------------|---------------------------------------------------|
| `n_taps` | 32 | N |
| `decimation` | 8 | R |
| `coefficients` | unit impulse | Q1.15 taps |
| `architecture` | `"classic"` | `"pipelined"` registers the memory operands |
| `prune_zeros` | `False` | Skip build-time zero taps in the schedule |

The output interval is `cycles_per_output = R + N + 1` clocks in the classic architecture: R
clocks to load the window, N clocks of MAC, one to drain the product register. The input rate is
therefore at most `R * f_clk / cycles_per_output`. The latency is N + 1.

The classic schedule registers each product before the accumulator, but in one clock the tap
address drives the asynchronous sample and coefficient memories and then the multiplier. The
pipelined architecture registers those three operands and multiplies on the next clock. The
arithmetic and the one-tap-per-clock scan are unchanged; the interval becomes R + N + 2 and the
latency N + 2.

```console
$ python3 -c "
from litedsp.filter.fir_poly import LiteDSPFIRDecimator as D
for a in ('classic', 'pipelined'):
    d = D(n_taps=32, decimation=8, architecture=a)
    print(a, d.cycles_per_output, d.latency)"
classic 41 33
pipelined 42 34
```

The extra register also lets Yosys map the DDC histories into block RAM. The classic architecture
is the default; the implementation registry selects `"pipelined"`, and the DDC exposes the same
choice as `fir_architecture` ([DDC](#gm-ddc)). The results of both are in
[Timing architecture](#perf-timing-arch).

The coefficients can be reloaded at run time through two registers. A write to `coeff_reset`
returns the write pointer to the first scheduled tap; each write to `coeff` stores one coefficient
and advances the pointer. The `config` status register returns N and R.

With `prune_zeros=True` the schedule and the coefficient memory hold only the non-zero taps given
at build time. The zero positions are structural: the reload interface cannot make them non-zero.
The half-band decimator uses this option.

### FIR interpolator {#fr-fir-interpolator}

`LiteDSPFIRInterpolator` emits L outputs per input. Output `p` comes from the polyphase sub-filter
`c[p::L]` over the recent inputs, `y[nL + p] = sum of c[p + kL] * x[n - k]`, so each output costs
one sub-filter of `ceil(N/L)` taps instead of N.

The default taps are a unit impulse; the
interpolators of the rate family load a low-pass with a gain of L, which makes up for the energy
spread over L outputs.

The classic architecture multiplies and accumulates in the same clock. The pipelined architecture
registers the memory operands and the product, then drains these two stages, two more clocks per
output, with the same output sequence and backpressure behaviour. Both report their schedule; for
the 65-tap interpolator by 8 of the DUC:

```console
$ python3 -c "
from litedsp.filter.fir_poly import LiteDSPFIRInterpolator as I
for a in ('classic', 'pipelined'):
    i = I(n_taps=65, interpolation=8, architecture=a)
    print(a, i.cycles_per_output, i.cycles_per_input, i.latency)"
classic 10 80 65
pipelined 12 96 67
```

The interpolator has no reload interface; its `config` status register returns N and L.

The classic architecture is the default of the API and the implementation registry selects the
pipelined one, for the DUC as for the decimator.

The four-DDC channelizer ([Channelizer](#gm-channelizer)) passes the same choice to its decimators.
At R=4 and 33 taps, the pipelined decimator raises the latency of each channel from 36 to 37 (the
decimator's 34 to 35, plus the 2 cycles of the mixer) and the output interval from 38 to 39 clocks.
[Timing architecture](#perf-timing-arch) gives the results of the DUC and of the bank in both
architectures.

### Half-band filters {#fr-halfband}

A half-band low-pass has its cutoff at a quarter of the sample rate, and every other tap except
the centre is zero ([Half-band filters](#pri-halfband)). `LiteDSPHalfbandDecimator` and
`LiteDSPHalfbandInterpolator` wrap the polyphase FIRs with `prune_zeros=True`, so the exact zeros
take neither MAC clocks nor coefficient memory. The taps come from `halfband_coefficients()`, 23 by
default; the interpolator design has a gain of 2.

```console
$ python3 -c "
from litedsp.filter.halfband import LiteDSPHalfbandDecimator, LiteDSPHalfbandInterpolator
d, i = LiteDSPHalfbandDecimator(), LiteDSPHalfbandInterpolator()
print('decimator', d.n_mac_taps, d.cycles_per_output)
print('interpolator', i.phase_mac_taps, i.cycles_per_input)"
decimator 13 16
interpolator (12, 1) 15
```

The default decimator schedules 13 products instead of 23, and completes an output every 16 clocks
instead of 26. The interpolator has 12 products for one phase and one for the other (the centre
tap), and completes both outputs of an input in 15 clocks instead of 26. The pruned zeros are not
writable through `core_coeff`.

The constant table of history offsets makes each clock slower than the rectangular schedule, but
each window takes ten fewer clocks, so the output capacity rises ([Filters](#perf-filter)).

Tests compare both directions with the complete unpruned model, bit for bit, under random stalls.

## CIC filters {#fr-cic}

A CIC filter decimates or interpolates by a large factor with adders only: N integrators at the
high rate, a rate change by R, N combs with a differential delay M at the low rate
([CIC filters](#pri-cic)). Its response is a sinc to the power N, with a passband droop that a
short FIR can compensate (`cic_comp_coefficients()`).

### Classic CIC {#fr-cic-classic}

`LiteDSPCICDecimator` and `LiteDSPCICInterpolator` use full-width wrap-around arithmetic, the
Hogenauer property: integrator overflows cancel in the combs as long as the registers are wide
enough. The registers are `data_width + ceil(N * log2(R*M))` bits wide. R, N and M are build-time
constants, so the rescale is a constant shift.

The CIC gain is `(R*M)**N` for the decimator and `(R*M)**N / R` for the interpolator. The output
is shifted right by `ceil(N * log2(R*M))` bits (the interpolator subtracts `log2(R)`), with
rounding and saturation. When `R*M` is a power of two the gain is exactly 1; otherwise the output
is smaller than the input by the ratio of the gain to the next power of two.

| Parameter | Default | Effect |
|------------------|---------|-----------------------------------------------------|
| `decimation` | 8 | R (`interpolation` for the interpolator), 2 or more |
| `n_stages` | 3 | N; sets the stopband and the droop |
| `diff_delay` | 1 | M, the comb delay |
| `staged` | `False` | Elastic one-adder stages, see below |

In the classic architecture the integrator cascade updates in a single clock, which gives a
latency of 1 and a long adder chain. The decimator accepts the R - 1 dropped samples freely and
stalls only on the sample that completes a window. The `config` status register returns R, N and
whether the block is staged.

The characterization compares the measured droop with the theoretical sinc response for R of 4, 8
and 16 and N of 3 and 4: the largest error recorded is 0.0 dB, measured on the golden models.

### Staged CIC {#fr-cic-staged}

The staged architecture (`staged=True`) registers every integrator and every comb. The figure
below shows the decimator: each accepted sample carries its decimation phase through one-adder
integrator stages, and only the marked sample of each window enters the one-subtractor comb
stages.

![Staged CIC decimator: elastic integrator stages at the input rate, the marked sample of each
window passes to the elastic comb stages, then round and saturate.](flt_cic_staged.svg)

Each stage is an elastic register: it accepts a new value when it is empty or when the next stage
takes its value. The numerical sequence is the same as the classic one; the latency becomes 2N
clocks and the throughput stays one sample per clock. The interpolator uses the reverse order:
combs, a zero-stuffing phase generator, then integrators.

The registry default is classic; the implementation and co-simulation registries select
`staged=True`, which [Timing architecture](#perf-timing-arch) compares with the classic one.

| Option | Throughput | Cost |
|---------------------------|-----------------------------|----------------------------------------|
| Classic | One sample per clock | Long adder chain, latency 1 |
| Staged | One sample per clock | Latency 2N clocks, N x W registers per axis |

### Runtime-rate CIC and bitstream decimator {#fr-cic-runtime}

`LiteDSPCICDecimatorRuntime` sizes its registers for a maximum rate `r_max` and takes the rate and
the rescale shift as run-time controls, `rate` and `shift`. The host writes them together, the
shift being `cic_shift(rate, N, M)`, so that the gain stays normalized. It works on a real or a
complex stream, and exposes `sample_ce` and `out_ce` strobes to drive a side accumulator in step
with the decimation window.

Its staged option chains the integrator registers and pipelines the combs and the rescale at the
decimated rate, `2N + 3` cycles per output. It requires `rate >= 2 * n_stages + 4`, so that an
output drains before the next window closes. The runtime CIC is not in the registry.

`LiteDSPBitstreamDecimator` turns a 1-bit stream from a sigma-delta modulator or a PDM microphone
into PCM samples. It maps each bit to +1 or -1 and runs the runtime CIC with a 2-bit input, so the
registers cost `2 + N * log2(r_max)` bits instead of a full sample width. A stream of all ones
comes out at full scale with the reset settings.

| Parameter | Default | Effect |
|--------------|--------------|--------------------------------------------------|
| `data_width` | 24 | Output PCM width |
| `decimation` | 64 | Reset value of `rate`, bits per output sample |
| `n_stages` | 4 | Sinc order: 3 for current sense, 4 or 5 for audio PDM |
| `r_max` | `decimation` | Largest run-time rate |
| `staged` | `False` | Staged runtime CIC |

The `rate` and `shift` registers change the decimation at run time; `bitstream_shift()` computes the
shift for a rate. A rate far below `r_max` would need a negative shift, which is clamped to 0 and
lowers the output scale, so choose `r_max` close to the rates in use. The motor-control current
sense and the audio PDM receiver of Part IV use this block ([Motor control](#motor),
[Audio](#audio)).

In the code: `litedsp/filter/cic.py`, `litedsp/filter/bitstream.py`.

## IIR and small filters {#fr-iir-small}

### IIR biquad {#fr-iir}

`LiteDSPIIRBiquad` is one second-order section in direct form II transposed, applied to I and Q
with shared coefficients ([IIR filters and biquads](#pri-iir)). The coefficients are a dictionary
of signed integers `b0`, `b1`, `b2`, `a1`, `a2` with `frac_bits` fractional bits (14 by default),
`a0` being 1. The default is a pass-through.

The feed-forward products `b*x` are registered in an intake stage, so the recursive loop carries
one multiply level per clock. The output and both state registers are rounded or saturated every
sample, which keeps a stable filter stable in fixed point. The state registers are
`data_width + frac_bits + 4` bits wide.

| Architecture | Accepts | Latency | Use |
|---------------|-----------------------------|---------|-------------------------------|
| `"classic"` | One sample per clock | 2 | Default |
| `"folded"` | One sample per three clocks | 4 | Higher clock rate, same results |

The folded architecture splits the recursion into three clocks: feed-forward and output, feedback
products, state update. It is bit-identical to the classic one. `LiteDSPIIRBiquadCascade` chains
sections from a list of coefficient dictionaries; its latency is the sum of theirs. The
coefficients are fixed at build time and the biquad has no registers.

```python
from litedsp.filter.design     import butterworth_sos, biquad_sos_quantize
from litedsp.filter.iir_biquad import LiteDSPIIRBiquadCascade

sections, frac = biquad_sos_quantize(butterworth_sos(4, 0.1))   # 4th order, cutoff 0.1 fs.
iir = LiteDSPIIRBiquadCascade(sections=sections, frac_bits=frac)
```

In the code: `litedsp/filter/iir_biquad.py`.

### Small filters {#fr-small-filters}

The remaining filters are short, mostly multiplier-free and of latency 1
([Moving average and DC blocker](#pri-small-filters), [Hilbert transformer](#pri-hilbert)):

| Block | Response | Control |
|----------------|----------------------------------------------|--------------------------------|
| DC blocker | First-order high-pass, notch at DC | `pole_shift` (5), `precision_bits` |
| Moving average | Mean of the last `2**length_log2` samples | `length_log2` (4) |
| Comb filter | Nulls at the multiples of fs/D | `depth` D (8) |
| Notch | Second order, zeros on the unit circle | `cos_w0` register, `r` (0.96) |
| Allpass | First order, flat magnitude | `a` register |
| Hilbert | Real input to analytic I/Q | `n_taps` (23, odd) |

The equations are, for the DC blocker, the comb filter and the allpass:

```text
DC blocker  y[n] = x[n] - x[n-1] + y[n-1] - (y[n-1] >> pole_shift)
Comb        y[n] = x[n] - x[n-D]
Allpass     y[n] = -a*x[n] + x[n-1] + a*y[n-1]
```

The DC blocker places a pole at `1 - 2**-pole_shift` with a single shift, so it needs no
multiplier. With the default `precision_bits=0` the recursion runs at `data_width` and a DC step
can leave a residual of up to `2**pole_shift - 1` LSBs.

With `precision_bits` = p, the state is p
bits wider, the leak is rounded away from zero and the output requantizer uses first-order error
feedback, so a DC step settles to exactly 0. The residual bound drops by 6.02 dB per bit, to about
-108 dBFS at `pole_shift=5`, p = 8, 16-bit. On the golden model the DC residual of the
characterization stimulus is exactly 0, reported as the 140 dB cap of the characterization.

The moving average keeps a running sum, adding the new sample and subtracting the one that leaves
the window, and outputs the rounded sum divided by the length: it is a one-stage CIC that does not
decimate. The DC blocker also has a mono variant for audio, `iq=False`, listed as "DC blocker
(mono)" in the catalogue.

The notch sets its frequency at run time: write `cos(2 pi f0)` to `cos_w0` in Q2.14. The pole
radius `r` is a build-time choice: closer to 1 gives a narrower notch, longer ringing and less
margin against quantization. The allpass coefficient `a` is in Q2.14 too; its reset value is 0.5.

The Hilbert block runs two FIRs of the same length on a real input. The I path is a pure delay of
`(n_taps - 1)/2` samples and the Q path is a type III Hilbert FIR, so I and Q stay aligned and the
negative-frequency image is suppressed. It has no registers.

The DC blocker, the moving average and the comb filter have the `bypass` control as a signal, with
no register; the notch and the allpass add a `bypass` register.

In the code: `dc_blocker.py`, `moving_average.py`, `extra.py` (notch, comb, allpass) and
`hilbert.py` in `litedsp/filter/`.

## Resamplers {#fr-resamplers}

### Farrow interpolator {#fr-farrow}

`LiteDSPFarrowInterpolator` delays a stream by a fraction of a sample. It interpolates between
samples at the position `mu`, an unsigned 15-bit fraction in [0, 1) (`frac_bits=15`), with a cubic
Catmull-Rom polynomial over a four-sample window ([Fractional delay and the Farrow
structure](#pri-farrow)). The coefficients are multiples of 1/2, so they need shifts only; the
polynomial is evaluated by Horner's rule.

The block outputs one sample per input. Each multiply and each add of the Horner evaluation has its
own register, with `mu` delayed alongside, so the latency is 7 and the throughput one sample per
clock. The `mu` register sets the delay at run time.

### Arbitrary resampler {#fr-arb}

`LiteDSPArbResampler` changes the sample rate by any ratio. A phase accumulator advances by
`ratio = f_in / f_out` for each output; each time its integer part increases, the window shifts by
one input sample. The output is the Catmull-Rom interpolation at the fractional phase.

The `ratio` register has `frac` fractional bits (15) and `ratio_int_bits` integer bits (8): 23 bits
with a reset value of `0x8000`, a ratio of 1.0. A ratio below 1 interpolates and a ratio above 1
decimates; a decimating resampler needs an anti-alias filter in front of it. Its latency is data
dependent.

### Rational resampler {#fr-rational}

`LiteDSPRationalResampler` resamples by L/M: a FIR interpolator by L, then a FIR decimator by M,
both built from the polyphase FIRs. The two filters share the cutoff `0.4/max(L, M)` of the
interpolated rate, below the ideal `0.5/max(L, M)` to leave a transition band. Each has about eight
taps per polyphase branch by default (`8*L + 1` and `8*M + 1`); the interpolator has a gain of L.

The registry configuration resamples by 3/2. The coefficients are built in, the resampler has no
registers and its latency depends on the phase.

### Pulse shaper {#fr-pulse-shaper}

`LiteDSPPulseShaper` is a FIR interpolator loaded with root-raised-cosine taps
(`rrc_coefficients()`). It maps one sample per symbol to `sps` samples per symbol with the
transmit half of a matched filter pair; the receiver runs a FIR with the same taps.

| Parameter | Default | Effect |
|-----------|---------|------------------------------------------------------------|
| `sps` | 4 | Samples per symbol, the interpolation factor |
| `span` | 8 | Span in symbols; `sps * span + 1` taps |
| `beta` | 0.35 | Roll-off; occupied bandwidth `(1 + beta)` times half the symbol rate per side |

The docstring of the block records the matched pair measured by `test/test_matched_pair.py` on
random QPSK: at the defaults, a worst symbol-spaced ISI sidelobe of -39.8 dB and an EVM of
-36.5 dB. The finite span sets this floor, not the tap quantization; a longer span lowers it at the
cost of taps and latency. Pulse shaping and matched filtering are explained in [Digital
communications](#comm-primer).

In the code: `farrow.py`, `arb_resampler.py`, `resampler.py` and `pulse_shape.py` in
`litedsp/filter/`.

## LMS equalizer {#fr-lms}

`LiteDSPLMSEqualizer` is an adaptive complex FIR: it filters the input with `n_taps` complex
weights and adapts them with the stochastic gradient update `w_k += mu * e * conj(x[n-k])`. The
error `e` depends on the run-time mode:

| Mode | Value | Error | Reference |
|-------------|-------|--------------------------------|-------------------------------------------|
| Trained | 0 | `d - y` | Sink fields `d_i`, `d_q`: training symbols or decisions |
| CMA | 1 | `y` times `R2 - abs(y)**2` | None (blind); target modulus in `cma_r2` |
| Decision | 2 | Nearest QPSK point minus `y` | Decision amplitude in `dd_level` |

The usual sequence is a blind CMA acquisition, then decision-directed tracking with a lower
misadjustment. Driving `train` low freezes the weights while the filtering continues. The weights
are signed Q`wint`.`wfrac` (Q4.14 by default) with the centre tap at 1.0; keep `wint + wfrac` at 18
or less so that each product fits an 18 by 18 DSP multiplier.

| Register | Width | Meaning |
|------------|-------|----------------------------------------------------------|
| `train` | 1 | 1 adapts (reset), 0 freezes the weights |
| `control` | 2 | Field `mode`: 0 trained, 1 CMA, 2 decision-directed |
| `cma_r2` | 17 | R2 with `data_width - 1` fractional bits |
| `dd_level` | 15 | Per-axis decision amplitude, positive |

For QPSK at a per-axis amplitude A, the docstring gives `cma_r2 = round(2*A**2 /
2**(data_width-1))`. The step size is `2**-mu_shift` (`mu_shift` = 20 by default), a plain shift.
The CMA error is saturated to the width of the trained error before the shift, which bounds the
weight step during acquisition; `cma_egain` scales the CMA error so that one step size suits both
modes.

The adaptation is delayed LMS. The classic architecture applies the error of the previous sample.
The pipelined architecture registers the FIR products, the sum, the scaled output, the squares,
the modulus, its error, the CMA product and the selected error, and applies the update after eight
accepted samples; `update_pipeline=True` adds a ninth. The output latency grows from 1 to 3 clocks
and the throughput stays one sample per clock.

The register cost is deliberate: each pending error carries its own snapshot of the tap window, so
a longer loop delay keeps the sample semantics exact under bubbles. The eight-sample and
one-sample loops are available too; the implementation registry selects the nine-sample option
([Timing architecture](#perf-timing-arch)). All modes, freezing and convergence are bit-exact
against the nine-sample model, and a Verilator co-simulation covers run-time mode switching.

In the code: `LiteDSPLMSEqualizer` and the `MODE_*` constants in `litedsp/filter/equalizer.py`.

## Rate family {#fr-rate}

### Rate wrappers {#fr-rate-wrappers}

The rate family wraps the filters into simple integer rate changers. `LiteDSPDecimator` and
`LiteDSPInterpolator` choose their filter with `method`:

| Method | Filter | Coefficients | Notes |
|----------|----------------------------|-------------------------------|------------------------------------|
| `"cic"` | CIC, `n_stages` = 4 | None | Default; large factors, droop |
| `"fir"` | Polyphase FIR decimator or interpolator | Windowed sinc, `8*R + 1` taps | Clean passband; `fir_architecture` |

With `method="fir"` the low-pass cutoff `cutoff` (0.4 by default) is given relative to the low
rate: the output rate of the decimator, the input rate of the interpolator. The interpolator FIR
has a gain of L. The wrappers expose the registers of their filter as `core_config` and, for the
FIR decimator, `core_coeff_reset` and `core_coeff`. The DDC and the DUC use them.

`LiteDSPDownsampler` and `LiteDSPUpsampler` change the rate without any filter, by a run-time
`factor` register (16 bits, reset 1). The downsampler keeps the first sample of each group of
`factor` and consumes the others freely. The upsampler emits `factor` samples per input, by
holding the value or, with `zero_stuff=True`, by inserting zeros. Pair them with a filter, as
`examples/ddc_chain.py` does with a FIR before a downsampler ([Decimation](#pri-decimation)).

In the code: `decimator.py`, `interpolator.py` and `dropper.py` in `litedsp/rate/`.

### Resampler farm {#fr-farm}

A serial-MAC decimator is idle most of the time at a low output rate, yet each instance pays for
its multipliers, accumulators and state machine. `LiteDSPResamplerFarm` shares one engine between
`n_channels` streams of the same rate. The figure below shows the structure.

![Resampler farm: per-channel sinks scanned in round robin, the sample histories in one
channel-major RAM, one shared complex MAC with the coefficient ROM or banks, and a channel-tagged
output for a demultiplexer.](flt_farm.svg)

Each channel behaves bit-exactly like its own `LiteDSPFIRDecimator`. The histories share one RAM
addressed by channel and pointer; the MAC (one multiplier per axis), the coefficient ROM and the
state machine are single. The engine scans the channels in a fixed round-robin order and waits for
each in turn, so all channels must run at the same average rate: a stalled channel stalls the farm.

The input is a list of `sinks`, one per channel. The output is a single stream with an extra
`channel` field, which `LiteDSPChannelDemux` fans out again:

```python
self.comb += [
    farm.source.connect(demux.sink, omit={"channel"}),
    demux.sel.eq(farm.source.channel),
]
```

One output costs `R + n_taps + 2` clocks in the classic architecture, and the aggregate input rate
over all channels is at most `f_clk * R / cycles_per_output`. The pipelined architecture registers
the RAM operands and the product, two more clocks per output, for the same output sequence. With
`channel_coefficients`, each channel has its own bank of taps; the `coeff_channel` register selects
the bank that `coeff_reset` and `coeff` write.

Four separate decimators would use eight DSP blocks; the farm keeps two, and the registered read
of the pipelined architecture lets ECP5 map the histories into block RAM. The classic architecture
and the shared ROM are the defaults; [Timing architecture](#perf-timing-arch) gives the results of
each option. The tests cover two to four channels, several tap counts and rates, independent stalls
per channel, channel isolation, the composition with the demultiplexer, and the reload of one bank
without disturbing the others.

In the code: `LiteDSPResamplerFarm` in `litedsp/rate/farm.py`.

## Parallel filters {#fr-parallel}

The parallel filters take `n_samples` lanes per beat, like the parallel NCO and mixer
([Parallel variants](#gm-parallel)), and produce the same samples as the serial blocks. They are
not in the registry and are tested against the serial models in `test/test_parallel.py`.

The parallel FIR filters, real and complex, take and give `n` lanes per beat; the parallel CIC
decimator gives one sample per beat.

The parallel FIR has `n_samples * n_taps` multipliers and a latency of 3; the complex one runs two
of them with shared taps. The decimation of the parallel CIC must be a multiple of `n_samples`. The
parallel FIR keeps a window of `n_taps - 1 + n_samples` samples that shifts by `n_samples` per
accepted beat, and computes one output per lane with its own products and adder tree.

The parallel CIC decimator integrates a whole beat per clock. Its staged option registers each
stage and computes the lane sums with an inclusive Kogge-Stone prefix scan, two adder levels for
four lanes, instead of a chain across the lanes. Both keep one beat per clock; the staged one adds
2N clocks of latency. Two lanes cost less when two samples per clock are enough; four lanes keep
the full aggregate rate for more logic.

The registry default is classic; both staged
configurations are 100 MHz timing sentinels of the implementation flow
([Timing architecture](#perf-timing-arch)).

In the code: `litedsp/filter/fir_parallel.py`, `litedsp/filter/cic_parallel.py`.

## Timing results {#fr-timing}

The families of this chapter that contain a feedback loop (CIC, FIR schedules, farm, LMS) offer a
faster architecture as a separate option, never as a change of the default; [Performance and
resources](#performance) gives the recorded results and how they are produced.

## Design helpers {#fr-design}

`litedsp/filter/design.py` computes coefficients at build time and in tests, with NumPy only. Each
function returns integers quantized to the Q format of the blocks, ready for a `coefficients`
parameter or a coefficient register; [Designing FIR taps](#pri-fir-design) explains the methods.

| Function | Result |
|------------------------------------|------------------------------------------------------|
| `firwin_lowpass` | Windowed-sinc low-pass, unity DC gain |
| `firwin_bandpass` | Windowed-sinc band-pass |
| `firwin_kaiser`, `kaiserord` | Kaiser-window low-pass from a ripple and a transition width |
| `remez`, `remez_lowpass` | Parks-McClellan equiripple linear-phase FIR |
| `halfband_coefficients` | Half-band low-pass, odd length |
| `hilbert_coefficients` | Type III Hilbert FIR, odd length |
| `rrc_coefficients` | Root-raised cosine |
| `gaussian_coefficients` | Gaussian pulse for GMSK and GFSK |
| `cic_comp_coefficients` | Inverse-sinc droop compensation for a CIC |
| `butterworth_sos` | Butterworth sections, float |
| `chebyshev1_sos`, `chebyshev2_sos` | Chebyshev type I and II sections, float |
| `biquad_sos_quantize` | Sections to integer biquad dictionaries |
| `polyphase_split` | Taps of each polyphase branch |
| `freq_response`, `report` | Response and figures of merit of the quantized taps |

`report()` gives the passband ripple, the stopband attenuation and the DC gain of the actual
quantized taps, the numbers to compare against a specification:

```python
from litedsp.filter.design import remez_lowpass, report

taps = remez_lowpass(63, 0.10, 0.15, data_width=16)
print(report(taps, 0.10, 0.15, data_width=16))
```

The functions use NumPy, a dependency of the package.

## Where to go next {#fr-next}

[Generation, mixing and correction](#generation-mixing) uses these filters in the DDC, DUC and
channelizers; [Level control and analysis](#level-analysis) follows them in a receiver;
[Verification](#verification) explains the golden models and co-simulation behind the tests cited
here.
