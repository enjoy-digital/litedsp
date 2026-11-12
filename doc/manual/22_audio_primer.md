# Digital audio in a nutshell {#audio-primer}

This chapter explains the signal path of a digital audio product to an FPGA engineer who has never
built one. It covers the sample format and the serial links first, then the converters, then the
processing: equalization, dynamics, level, effects, word-length reduction and loudness metering.

Each section ends with the LiteDSP block that implements the idea. [Audio blocks](#audio) then
describes the blocks, their conventions and their clock budget.

## PCM samples, levels and headroom {#apri-pcm}

Digital audio is pulse-code modulation (PCM): a stream of signed samples at a fixed sample rate,
one stream per channel. The common rates are 44.1 kHz and 48 kHz, with multiples for high
resolution audio. The sample format is two's complement, 16 or 24 bits.

Levels are given in dBFS, decibels relative to the full-scale sample ([Measuring
quality](#pri-metrics)). A full-scale sine is 0 dBFS. Headroom is the distance between the
working level and full scale; it absorbs peaks so that they do not clip.

The audio band is the range of human hearing, about 20 Hz to 20 kHz. The quality figures of an
audio chain are measured in that band: THD+N, the total harmonic distortion plus noise relative to
the signal, and the dynamic range, the distance between full scale and the noise floor.

In LiteDSP, audio samples are signed Q1.23 in a 24-bit `data` field by default. Every audio block
is parameterized by `data_width`, so a 16-bit or a 32-bit chain uses the same blocks.

## Channels on one stream {#apri-channels}

A stereo signal has two channels, a surround signal more. An audio rate is thousands of times below
an FPGA clock, so one processing engine can serve all the channels in turn. LiteDSP carries them
on one stream: each beat holds one sample and a `channel` tag, and the beats of one frame follow
each other in channel order.

This is a *time-division multiplexed* (TDM) stream, `tdm_layout`. Left is channel 0 and right is
channel 1. With one channel, the layout degenerates to the plain `real_layout` mono stream.

## Serial audio links: I2S, justified and TDM {#apri-i2s}

Audio converters and codecs exchange samples over a three-wire serial link. A bit clock (BCLK)
times the bits; a word clock (LRCK, also called frame sync) marks the frames; a data line (SDATA)
carries the bits, most significant first. One device, the *master*, drives the clocks; the other,
the *slave*, follows them.

Each frame has one *slot* per channel, of 16, 24 or 32 bits. A sample may be shorter than its
slot, and the formats differ in where the sample sits inside the slot. The figure below shows one
I2S frame.

![One I2S frame. LRCK low selects the left slot and LRCK high the right slot; the most significant
bit of each sample follows the LRCK edge by one bit clock, and the unused low bits of the slot are
padding.](apri_i2s.svg)

| Format | Word clock | Sample position |
|-------------------|-------------------------------------|------------------------------------------|
| I2S | Left while LRCK is low | MSB one BCLK after the LRCK edge |
| Left-justified | Left while LRCK is high | MSB at the LRCK edge |
| Right-justified | Left while LRCK is high | LSB at the end of the slot |
| TDM | One-BCLK sync pulse per frame | 2, 4 or 8 consecutive slots |

The bit clock is the sample rate times the bits per frame. Two 32-bit slots at 48 kHz give a
3.072 MHz BCLK. The LiteDSP converters, `LiteDSPI2SReceiver` and `LiteDSPI2STransmitter`, handle
the four formats in master and slave modes.

## PDM microphones and sigma-delta conversion {#apri-pdm}

Digital MEMS microphones output a *pulse-density modulated* (PDM) signal: a 1-bit stream at a few
MHz whose density of ones follows the sound pressure. The microphone contains a sigma-delta
modulator; the receiver must decimate the bitstream back to PCM.

A sigma-delta modulator trades amplitude resolution for rate. It quantizes to one bit, feeds the
quantization error back and subtracts it from the next input. The error is thereby pushed to high
frequencies: *noise shaping*. A first-order loop shapes the noise by `(1 - z^-1)`, a second-order
loop by `(1 - z^-1)^2`.

The ratio of the bit rate to the audio sample rate is the oversampling ratio (OSR). A decimator
removes the shaped noise above the audio band and lowers the rate by the OSR. A sinc filter, a
CIC decimator, does it cheaply ([CIC filters](#pri-cic)); its passband droop can be corrected by a
short compensation FIR.

Two microphones can share one data line. One drives it after the rising edge of the microphone
clock and the other after the falling edge, so the receiver samples both edges. LiteDSP
implements the receive side in `LiteDSPPDMReceiver`, with this dual-edge mode for stereo pairs.

The same principle works in reverse as a DAC. A digital sigma-delta modulator turns PCM into a
1-bit stream, which an output pin and an analogue low-pass filter turn into a voltage. LiteDSP
provides the modulator, `LiteDSPSigmaDeltaModulator`, and a PDM DAC built on it.

A second-order loop is only conditionally stable: a large input overloads its integrators. The
LiteDSP modulator documents keeping the input below about -3 dBFS.

## Equalization with biquads {#apri-eq}

An equalizer (EQ) shapes the frequency response: it boosts or cuts bass, treble or a band. Each
band is a second-order IIR section, a *biquad* ([IIR filters and biquads](#pri-iir)). Three types
cover most uses.

| Band type | Effect | Parameters |
|-------------------|--------------------------------------------|-------------------------------|
| Low shelf | Raises or lowers everything below `f0` | `f0`, gain, slope or Q |
| High shelf | Raises or lowers everything above `f0` | `f0`, gain, slope or Q |
| Peaking | Boosts or cuts a band around `f0` | `f0`, gain, Q |

The coefficients come from the closed formulas of the widely used audio EQ cookbook. LiteDSP
implements them in `rbj_biquad()` of `litedsp/audio/design.py`, together with low-pass,
high-pass, band-pass, notch and all-pass sections and Linkwitz-Riley crossovers.

Low-frequency bands are hard in fixed point: a 40 Hz shelf at 48 kHz has its poles very close to
the unit circle, so the rounding noise of the feedback is amplified by a large gain. The LiteDSP
equalizer, `LiteDSPAudioEQ`, uses Q4.28 coefficients and first-order *error feedback*, which
shapes that noise by `(1 - z^-1)` ([IIR filters](#pri-iir)).

## Dynamics: compressor, limiter and gate {#apri-dynamics}

A dynamics processor changes the gain according to the level of the signal. A *compressor* reduces
the gain above a threshold, by a ratio: with 4:1, a level 8 dB above the threshold leaves 2 dB
above it. A *limiter* is a compressor with an infinite ratio, a ceiling.

A *gate* or *expander* reduces the gain below the threshold, to mute noise between passages.

The static behaviour is a line in decibels: below the threshold the output follows the input;
above it the slope is `1/ratio`. A level detector feeds the gain computer, either the peak of the
signal or its RMS value. The figure below shows the parts.

![A dynamics processor. A side chain measures the level, computes the gain reduction in the log
domain and smooths it with attack and release times; the gain multiplies the main path, which a
lookahead delay can hold back so that a limiter acts before the peak.](apri_dynamics.svg)

Working in the log domain makes the gain computer simple: the gain reduction is a slope times the
excess over the threshold, in dB. The gain is then smoothed: a short *attack* time reacts to a
rising level, a longer *release* time recovers after it.

A limiter must act before a peak passes, but a detector only sees a peak when it arrives. A
*lookahead* delay holds back the main path while the side chain sees the undelayed signal, so the
gain has already dropped when the peak reaches the multiplier.

In LiteDSP, `LiteDSPCompressor` implements the three behaviours; its presets only set the reset
values of the controls. Its log-domain gain computer works in log2 units of Q.8, where 256
represents 6.02 dB.

## Level, panning and mid/side {#apri-level}

A volume control multiplies each channel by a gain. Changing that gain in one step produces an
audible click on a loud signal, called *zipper noise*. A volume control therefore ramps the gain
toward its new value over many samples. A mute is a ramp to zero.

A *stereo matrix* computes each output channel as a weighted sum of both input channels. Panning a
mono source, adjusting the stereo width, swapping channels, folding to mono and mid/side coding
are all particular matrices. Mid/side coding gives `M = (L + R)/2` and `S = (L - R)/2`.

Constant-power panning keeps the perceived loudness constant: the left and right gains are the
cosine and the sine of a quarter-circle angle. LiteDSP provides the matrices in
`litedsp/audio/design.py` and applies them with `LiteDSPStereoMatrix`.

## Delay-based effects {#apri-effects}

A *delay line* stores past samples and plays them back after a fixed time. With feedback, it
produces an echo that repeats and decays; a low-pass filter in the feedback path, the *damping*,
makes each repeat duller, as in a real room.

Modulating the delay with a slow oscillator gives *chorus*, *flanger* and *vibrato*. The
modulated delay is fractional, so the delay line interpolates between two stored samples. The slow
oscillator is a low-frequency oscillator (LFO), an NCO at a few hertz ([The NCO](#pri-nco)).

A *reverb* simulates the dense echoes of a room. A common structure, the Schroeder reverb, sums
several parallel feedback combs and passes the sum through series all-pass filters, which thicken
the echoes without colouring the spectrum. LiteDSP builds its reverb from its delay line.

## Dither and noise shaping {#apri-dither}

Reducing a 24-bit chain to a 16-bit output drops eight bits. Plain rounding makes the error depend
on the signal: a quiet tone then shows harmonic distortion rather than noise. *Dither* adds a small
random signal before the requantization, so that the error becomes signal-independent noise.

Triangular dither (TPDF), the sum of two independent uniform random values spanning plus or minus
one output LSB, makes the error noise independent of the signal. It costs a slightly higher noise
floor, which is the accepted price for a distortion-free output.

*Noise shaping* then moves that noise out of the most audible band. Error feedback of the previous
requantization errors gives a noise transfer of `(1 - z^-1)` or `(1 - z^-1)^2`: the noise drops at
low frequencies and rises near half the sample rate. The total noise is higher, but the in-band
noise is lower. The LiteDSP requantizer is `LiteDSPDither`.

## Metering and loudness {#apri-metering}

A *peak meter* shows the magnitude of the largest recent sample, with a slow fall-back so the eye
can read it, a *hold* value of the largest peak, and a *clip* count of samples at full scale. The
LiteDSP meter, `LiteDSPPeakMeter`, keeps them per channel and converts the peaks to log2 units for
the host.

Peak level says little about how loud a programme sounds. Recommendation ITU-R BS.1770 defines a
*loudness* measure. A K-weighting filter, a high shelf followed by a high-pass, approximates the
sensitivity of the ear; the weighted mean square of all channels gives the loudness in LKFS.

BS.1770 measures over 400 ms blocks that overlap by 75 %. *Integrated* loudness averages the
blocks of the whole programme, with a gate that ignores silent and much quieter blocks. Meters
add a *momentary* value over the last 400 ms and a *short-term* value over the last 3 s. In
LiteDSP, `LiteDSPLoudness` accumulates the K-weighted squares and the host driver computes the
three values ([Audio blocks](#audio)).

Where to go next: [Audio blocks](#audio) for the implementation, [Radar and sonar
primer](#radar-primer) for the next family.
