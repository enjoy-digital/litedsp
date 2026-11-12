# Radar and sonar in a nutshell {#radar-primer}

This chapter explains pulse-Doppler radar and active sonar to an FPGA engineer who knows sampling
and filters but has never built a radar receiver. It follows one echo from the transmitted pulse
to a confirmed track: range, pulse compression, clutter cancellation, Doppler processing,
detection, peak extraction and tracking, then arrays and sonar.

Each section gives the idea and the formula the blocks use, and ends with the LiteDSP block that
implements it. [Radar and sonar blocks](#radar) describes the blocks themselves. Sampling, I/Q
and fixed point are in [Sampled signals and fixed point](#dsp-primer), FIR filters in [Digital
filters](#filter-primer), the chirp generator and the FFT in [Oscillators, mixers and the
FFT](#spectral-primer).

## Echoes and range {#rpri-range}

A radar sends a short burst of radio energy, a *pulse*, and listens for its echoes. An object at
distance `R` returns the pulse after the round trip time `t = 2 R / c`, with `c` the speed of
light. Measuring the delay of an echo therefore measures the distance to the object: its
*range*.

The receiver samples the echoes at the rate `fs`. One sample period covers a range interval of
`c / (2 fs)`, the *range bin*: at `fs = 100 MHz`, one bin is 1.5 m. A sonar works the same way
with sound in water: `c` becomes the speed of sound and the bins are much shorter.

The figure below places the whole chain on one line. The first stages work on each pulse as it
arrives, the middle ones on each range bin across the pulses, the last ones on a short list of
targets.

![The stages of a pulse-Doppler receiver. Pulse compression and clutter cancellation work in
fast time, Doppler processing and detection on the range-Doppler map, peak extraction and
tracking on sparse records once per CPI.](rpri_chain.svg)

In LiteDSP, the host helper `range_bin_metres(sample_rate, propagation_speed)` of
`litedsp.radar.design` gives the size of a bin in metres; pass the speed of sound for a sonar.

## Pulses, PRI and CPI {#rpri-timing}

A pulse-Doppler radar repeats its pulse at a fixed period, the *pulse repetition interval* (PRI);
its inverse is the *pulse repetition frequency* (PRF). After each transmit pulse the receiver
opens a *receive window* and samples the echoes of that pulse. The figure below shows the
timing.

![Pulse timing. Each PRI starts with the transmit pulse (Tx) and continues with the receive
window, whose samples are the range bins of that pulse. M consecutive PRIs form a coherent
processing interval (CPI).](rpri_timing.svg)

An echo that arrives after the next pulse has left is attributed to the wrong pulse, so the PRI
bounds the *unambiguous range* to `c PRI / 2`. A group of `M` consecutive pulses processed
together is a *coherent processing interval* (CPI). The Doppler processing of [Doppler
processing](#rpri-doppler) needs all `M` pulses of a CPI.

In LiteDSP, the range gate counts the PRI in input samples, frames the receive window as one
stream frame per pulse and signals the start of each CPI (`LiteDSPRangeGate`). The pulse
generator produces the transmit pulse train (`LiteDSPPulseGenerator`).

## Pulse compression {#rpri-compression}

A short pulse separates close targets but carries little energy; a long pulse carries energy but
blurs the range. *Pulse compression* gets both. The radar transmits a long pulse whose frequency
sweeps a bandwidth `B` during the pulse, a *linear FM chirp*, and the receiver correlates the
echoes with a copy of that pulse.

The correlator is a *matched filter*: an FIR filter whose taps are the conjugate, time-reversed
transmitted pulse.

Its output peaks where the echo aligns with the reference, and the width of that peak depends on the
bandwidth, not on the pulse length. With `B` in cycles per sample, the -3 dB width of the compressed
peak is about `0.886 / B` samples.

The product of the pulse length and the bandwidth, the *time-bandwidth product*, sets the gain
of the compression. The compressed peak has sidelobes, about 13.2 dB below the peak for an
unweighted chirp: the *peak-to-sidelobe ratio* (PSLR). A window on the reference (Hann, Hamming,
Blackman) lowers the sidelobes and widens the main lobe, as for any windowed FIR.

In LiteDSP, the chirp source is `LiteDSPChirp` and `litedsp.radar.waveform` computes its
frequency words and its bit-exact reference. The pulse compressor runs the matched filter on two
complex FIRs (`LiteDSPPulseCompressor`).

## Fast time and slow time {#rpri-matrix}

The samples of one pulse, range bin after range bin, are the *fast time*. The same range bin
seen from pulse to pulse is the *slow time*. A CPI is therefore a matrix of `M` pulses by `N`
range bins, as the figure below shows.

![The data of one CPI. Each row is one pulse, sampled in fast time from range bin 0 to N-1; each
column is one range bin seen across the M pulses, in slow time. Doppler processing works on the
columns.](rpri_cube.svg)

The receiver produces the matrix row by row, but the Doppler processing needs it column by column.
Reordering a CPI from rows to columns is the *corner turn*: a memory written in pulse order and read
in range-bin order.

It holds `N x M` complex samples, twice that when it double-buffers to accept the next CPI while the
current one is read.

In LiteDSP, the corner turn is a ping-pong RAM of two CPIs (`LiteDSPCornerTurn`).

## Clutter and MTI {#rpri-mti}

Echoes from the ground, buildings or the sea surface, the *clutter*, are often much stronger than
the targets. Clutter does not move, so its echo keeps the same phase from pulse to pulse, while
the phase of a moving target turns. A *moving target indicator* (MTI) filter removes what does
not change across pulses.

The two-pulse canceller subtracts the previous pulse, range bin by range bin: `y = x - x1`. The
three-pulse canceller applies `y = x - 2 x1 + x2` and widens the clutter notch.

A target whose phase turns by `f` cycles per pulse is weighted by `|2 sin(pi f)|` with two pulses
and by `4 sin^2(pi f)` with three. Targets with an integer `f` cancel too: these are the *blind
speeds*.

In LiteDSP, the MTI canceller keeps the previous pulses in RAMs indexed by range bin
(`LiteDSPMTICanceller`). The clutter map of [Detection and CFAR](#rpri-cfar) is the other answer
to clutter.

## Doppler processing {#rpri-doppler}

A target moving at radial velocity `v` shifts the echo frequency by the *Doppler frequency* `fd = 2
v / lambda`, with `lambda` the wavelength.

Within one pulse the shift is invisible; from pulse to pulse it turns the phase of the range bin by
`2 pi fd PRI`. An FFT over the `M` samples of a slow-time column separates the targets by velocity.

Doppler bin `k` of an `M`-point FFT holds the frequency `k PRF / M`. In natural FFT order, bins
`k >= M/2` are negative frequencies: targets moving away. The velocity is `fd lambda / 2`, and
the measurement wraps beyond `+/- PRF / 2`. A window over the pulses lowers the Doppler
sidelobes, as in any spectral analysis.

The detector needs a level, not a phase. The *magnitude* `sqrt(i^2 + q^2)`, or its cheap
alpha-max-beta-min approximation, or the *power* `i^2 + q^2` turns each complex bin into a
non-negative *cell*. The cells of all range bins form the *range-Doppler map*.

In LiteDSP, the Doppler processor chains a window, an FFT, a magnitude or power stage and a
reorder to natural order (`LiteDSPDopplerProcessor`). `doppler_bin_velocity(bin_index, n_pulses,
prf, wavelength)` converts a bin to a velocity on the host.

## Detection and CFAR {#rpri-cfar}

A detector compares each cell of the map with a threshold. A fixed threshold fails, because the
noise and clutter level changes with range, direction and weather. A *constant false alarm rate*
(CFAR) detector estimates the local noise from the neighbouring cells and scales the threshold
from it, so the probability of a false alarm stays constant.

The figure below shows a one-dimensional CFAR window. The *cell under test* (CUT) sits in the
middle. The *guard cells* next to it are ignored, because a target spreads into them. The
*training cells* on both sides give the noise estimate.

![One-dimensional CFAR. The mean of the training cells, multiplied by alpha, is the threshold;
the cell under test is detected when it exceeds it. The guard cells keep the target's own energy
out of the noise estimate.](rpri_cfar.svg)

The variants differ in the noise estimate, as the table below shows.

| Variant | Noise estimate | Suited to |
|-------------------------|------------------------------------------|----------------------------------|
| CA, cell averaging | Mean of all training cells | Uniform noise |
| GO, greatest of | Larger of the leading and lagging means | Clutter edges |
| SO, smallest of | Smaller of the two means | Two close targets |
| OS, ordered statistic | The k-th smallest training cell | A target among the training cells |

The multiplier `alpha` follows from the wanted false alarm probability `Pfa` and the number of
training cells `N`. For power cells, the exact cell-averaging value is
`alpha = N (Pfa^(-1/N) - 1)`. For magnitude cells, LiteDSP uses the asymptotic value
`alpha = sqrt(-4 ln(Pfa) / pi)` of Rayleigh-distributed noise.

A two-dimensional CFAR slides a box over the range-Doppler map instead of a line: training
cells in range and in Doppler, and a guard box around the cell under test. A *clutter map*
works across scans instead: it keeps an average per cell over many CPIs and detects a cell that
rises above its own history.

In LiteDSP, `cfar_alpha(pfa, n_train_cells, domain)` computes `alpha`. The detectors are
`LiteDSPCACFAR` (CA, GO, SO), `LiteDSPOSCFAR`, `LiteDSPCFAR2D` and `LiteDSPClutterMap`.

## Peaks and sub-bin interpolation {#rpri-peaks}

A strong target exceeds the threshold in several neighbouring cells. *Peak extraction* keeps one
detection per target: a detected cell becomes a target when it is the local maximum of its 3 x 3
neighbourhood.

The true position of a target lies between bins. A parabola through the peak `y0` and its two
neighbours `y_prev` and `y_next` gives the offset `(y_next - y_prev) / (2 (2 y0 - y_prev -
y_next))`, between -0.5 and +0.5 bin, along each axis.

The result is a short list of targets per CPI, each with a range, a Doppler and a level.

In LiteDSP, the peak extractor finds the local maxima and interpolates them
(`LiteDSPPeakExtractor`); the target list buffers each CPI's list for the host
(`LiteDSPTargetList`).

## Tracking {#rpri-tracking}

Detections are noisy and include false alarms. A *tracker* links the detections of successive
CPIs into tracks, filters their position and estimates their velocity. Each track predicts where
its target will be at the next CPI. A detection inside a *gate* around the prediction is
*associated* with that track, the nearest one first.

The *alpha-beta filter* corrects the prediction with the measurement error `e`: `P = pred + alpha e`
for the position, `V = V + beta e` for the velocity, then `pred = P + V`.

The *tracking index* `lambda`, the ratio of the process noise to the measurement noise, gives the
optimal steady-state pair `(alpha, beta)`. A *Kalman filter* derives the gains from a covariance at
each update instead of using fixed ones.

A new detection starts a *tentative* track. The track is *confirmed* after a number of hits,
*coasts* on its prediction when a detection is missing, and is deleted after too many misses in
a row. False alarms start tentative tracks that die before they confirm.

In LiteDSP, `alpha_beta_from_index(tracking_index)` gives these gains; the trackers are
`LiteDSPAlphaBetaTracker` and `LiteDSPKalmanTracker`.

## Arrays and angle {#rpri-arrays}

An array of `n` antennas or hydrophones spaced by `d` sees a plane wave from angle `theta` with a
phase step of `2 pi (d / lambda) sin(theta)` from one element to the next.

A *beamformer* weights each element with the opposite phase and sums them, so the array points at
`theta`. The weights `w[e] = exp(-j 2 pi (d / lambda) e sin(theta)) / n`, optionally tapered, form
one *beam*; several weight sets form several beams.

*Phase-comparison monopulse* measures the angle directly. Two half-arrays see the same echo with
a phase difference that depends on the angle. The phase of `a * conj(b)` is that difference, and
the host turns it into an angle with the spacing and the wavelength.

In LiteDSP, `steering_weights(n_elements, angle_deg, d_over_lambda, taper)` computes the weights;
the blocks are `LiteDSPBeamformer` and `LiteDSPMonopulse`.

## Sonar and time-varying gain {#rpri-sonar}

Active sonar uses the same chain at much lower sample rates, with one more concern: the echo
loses level quickly with range. Spherical spreading costs 20 dB per decade of range each way,
40 dB per decade for the round trip, and absorption adds a loss proportional to the range.

*Time-varying gain* (TVG) compensates this loss along each ping. The receiver gain rises with the
range bin `r` following `g0 + k_log log2(r) + k_lin r` in the log domain. After TVG, a target
has the same level at any range and the detector sees a flat background.

In LiteDSP, `tvg_coefficients(db_per_decade, alpha_db_per_bin, g0_db)` turns a law in dB into the
words of `LiteDSPTVG`.

## Where to go next {#rpri-next}

The blocks, their streams and their host helpers are in [Radar and sonar blocks](#radar); the
image family starts with [Images and video in a nutshell](#image-primer).
