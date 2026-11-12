# Audio blocks {#audio}

The `litedsp/audio/` family covers the signal path of a digital audio product on the same stream
contract as the RF and motor blocks. It has converters (I2S, PDM microphones, sigma-delta DACs),
tone and dynamics processing, effects, metering and word-length reduction. This chapter gives the
conventions, the two engine styles and their clock budget, the blocks by stage, the host math and
the AN010 application note.

It assumes the concepts of [Audio primer](#audio-primer). Every block follows [Block
contract](#architecture), has a bit-exact NumPy golden model and, where the generic testbench
applies, a Verilator co-simulation.

## At a glance {#aud-glance}

| Stage | Blocks | Files (`audio/`) |
| ------------------ | ------------------------------------------------------- | --------------------------- |
| Converters | `LiteDSPI2SReceiver`, `LiteDSPI2STransmitter`, `LiteDSPPDMReceiver`, `LiteDSPSigmaDeltaModulator`, `LiteDSPSigmaDeltaDAC` | `i2s.py`, `pdm.py` |
| Tone | `LiteDSPAudioEQ` | `eq.py` |
| Dynamics | `LiteDSPCompressor` (compressor, limiter, gate) | `dynamics.py` |
| Level | `LiteDSPVolume`, `LiteDSPStereoMatrix` | `level.py` |
| Effects | `LiteDSPLFO`, `LiteDSPDelayLine`, `LiteDSPWetDryMix`, `LiteDSPReverb` | `effects.py` |
| Metering | `LiteDSPPeakMeter`, `LiteDSPLoudness` | `meter.py` |
| Requantization | `LiteDSPDither` | `dither.py` |

The host design helpers are in `litedsp/audio/design.py`.

The family has 19 registry entries from 16 classes. Three of them reuse a class with other
defaults: `limiter` and `noise_gate` are `LiteDSPCompressor` presets (the limiter also with 32
frames of lookahead), and `chorus` is `LiteDSPDelayLine` with modulation.

Each entry has a datasheet in the online catalogue ([block
index](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md), section Audio
Processing), and its registers are in [Audio](#reg-audio). The status is in the [status
table](#intro-status); the out-of-context ECP5 synthesis results are in [Audio](#perf-audio) of
the performance appendix.

## Conventions {#aud-conventions}

The audio blocks share a sample format, one multi-channel stream and fixed formats for gains,
coefficients and time constants. The table below lists them.

| Item | Convention |
|----------------------|------------------------------------------------------------------------|
| Sample format | Signed Q1.23 in a 24-bit `data` field by default; every block is width-parameterized |
| Multi-channel audio | One channel-tagged TDM stream, `tdm_layout(data_width, n_channels)` |
| Volume gains | Unsigned Q5.(N-5), up to +30 dB |
| Mix and matrix | Signed Q1.15 (wet/dry, delay) or Q3.15 (stereo matrix) |
| Dynamics | Log2 domain, Q.8: 256 is 6.02 dB |
| EQ coefficients | Q4.28, from `biquad_sos_quantize(rows, 32, 28)` |
| Time constants | One-pole coefficients Q0.16, from `time_constant_coeff(ms, sample_rate)` |
| Bypass | In-line layout-preserving blocks pass beats through exactly, tag included |

The TDM stream is described in [Channels on one stream](#apri-channels); the figure below shows a
stereo stream.

![A channel-tagged TDM stream. Each beat carries one sample and its channel tag; a stereo frame
is a left beat followed by a right beat, so one engine processes both channels in turn.](aud_tdm.svg)

The coefficient designs come from `litedsp.audio.design`, and `biquad_sos_quantize()` is the
filter-family helper of `litedsp/filter/design.py`.

## Two engine styles {#aud-engines}

*Pipelined blocks* accept one beat per clock: volume, dither, the meters, the wet/dry mix, the TDM
mux and demux, and the bitstream decimator. *Serial engines* time-multiplex one multiplier over a
few cycles per beat and declare the budget as `cycles_per_sample`.

An audio stream is slow compared to the fabric clock, so the budget only bounds the lowest system
clock. The table gives the cycles of each serial engine, read from the code, and the clock they
need for 48 kHz stereo, that is 96 000 beats per second.

| Block | Cycles per beat | Lowest `sys_clk` at 48 kHz stereo |
|-----------------------------|------------------------|-----------------------------------|
| `LiteDSPAudioEQ`, 3 bands | 26 (`8·n_bands + 2`) | 2.5 MHz |
| `LiteDSPCompressor` | 16 | 1.6 MHz |
| `LiteDSPStereoMatrix` | 8 per frame | 0.4 MHz |
| `LiteDSPDelayLine` | 8, or 10 modulated | 0.8 MHz, or 1.0 MHz |
| `LiteDSPLoudness` side EQ | 18 (2 bands) | 1.8 MHz |

The reverb is a composite of delay-line engines: its combs run in parallel and its all-passes
follow each other on streams, so each engine works on its own beat. Serial engines apply
backpressure while busy.

A tap that must never stall the line works differently. `LiteDSPLoudness` drops a beat that
arrives while its side engine is busy and sets a sticky `overrun` flag instead.

## Converters and clocking {#aud-converters}

All the converters run in the `sys` clock domain: they sample or drive the audio pins with
`sys_clk` and need no audio clock domain. This section gives the clocking rule of each one.

### I2S, justified and TDM {#aud-i2s}

The I2S receiver and transmitter, `LiteDSPI2SReceiver` and `LiteDSPI2STransmitter`, support the
four formats of [Serial audio links](#apri-i2s) through `fmt`: `"i2s"`, `"left_justified"`,
`"right_justified"` and `"tdm"`. The `mode` parameter selects master or slave.

A master divides `sys_clk` by `bclk_div`, an even value of at least 4, to make BCLK, and drives
LRCK and SDATA on the falling edge. A slave synchronizes BCLK, LRCK and SDATA with two flip-flops
and detects their edges. It therefore needs `sys_clk` of at least 4 times BCLK to receive and 8
times BCLK to transmit.

| Parameter | Values | Meaning |
|--------------------|--------------------------|--------------------------------------------------|
| `fmt` | four formats | Frame format |
| `mode` | `"master"`, `"slave"` | Who drives BCLK and LRCK |
| `slot_width` | 16, 24, 32 | Bits per slot |
| `sample_width` | 8 to `min(slot_width, data_width)` | Bits per sample, MSB-aligned into `data_width` |
| `n_channels` | 2; 2, 4 or 8 in TDM | Slots per frame |
| `bclk_div` | even, at least 4 | Master BCLK divider |

The receiver tags each word with its slot. A word that completes while the previous one is unread
is dropped and sets the sticky `overrun`. The transmitter fills a frame buffer by tag and commits
it at each frame start; a frame start without a complete buffer repeats the previous frame and
sets the sticky `underrun`.

The transmitter rounds and saturates samples from `data_width` to `sample_width`. In TDM, the
frame carries 2, 4 or 8 slots after a one-BCLK sync pulse.

### PDM microphones {#aud-pdm}

The PDM receiver, `LiteDSPPDMReceiver`, drives the microphone clock at `sys_clk/clk_div` and
samples the data line after the falling edge and, by default (`dual_edge=True`), also after the
rising edge, so one data line carries two channels. The figure below shows its chain.

![The PDM receiver. The bitstream interface drives the microphone clock and samples the data
line; one sinc decimator per channel, an optional DC blocker and an optional droop-compensation
FIR produce PCM, which a TDM mux interleaves into one tagged stream.](aud_pdm.svg)

Each channel has its own bitstream decimator, a sinc^N filter of `n_stages` (4 by default) and
`decimation` (64 by default). A mono DC blocker per channel removes the offset, and an optional
compensation FIR of `n_comp_taps` flattens the sinc droop. The output is a TDM stream at
`sys_clk/(clk_div·decimation)` frames per second.

The interface's sticky `overrun` flags a bit dropped by backpressure. The `dual_edge` mode needs
an even number of channels.

### Sigma-delta DAC {#aud-dac}

The sigma-delta modulator, `LiteDSPSigmaDeltaModulator`, turns `real_layout` samples into a 1-bit
stream at `interpolation` bits per sample, with zero-order hold. Its `order` is 1 or 2, error
feedback with the noise transfer `(1 - z^-1)^order`. Keep the input below about -3 dBFS for the
second-order loop.

The PDM DAC, `LiteDSPSigmaDeltaDAC`, feeds one modulator per channel and clocks the bits out on
`pdm_out` at `sys_clk/clk_div`, with the clock on the `pdm_clk` pin. Feed it at
`sys_clk/(clk_div·interpolation)` frames per second. Once streaming has started, a starved tick
repeats the last bit and sets the sticky `underrun`.

## Equalizer {#aud-eq}

The equalizer, `LiteDSPAudioEQ`, cascades `n_bands` biquads per channel, all sharing one
multiplier. Per beat the engine runs the bands in sequence, 8 cycles each, from state and
coefficient memories.

Each section is direct-form I with a full-precision accumulator and error feedback of the rounding
error ([Equalization with biquads](#apri-eq)). The default `error_feedback=1` is first order; 2
is second order; 0 disables it. The state stays narrow: the four samples at `data_width` and the
error at `frac_bits`.

| Parameter | Default | Meaning |
|----------------------|-------------|------------------------------------------------------|
| `n_bands` | 3 | Biquads per channel |
| `n_channels` | 2 | Channels of the TDM stream |
| `coeff_width` | 32 | Coefficient width |
| `frac_bits` | 28 | Coefficient fractional bits, Q4.28 |
| `sections` | passthrough | Initial coefficients, one dict per band |
| `error_feedback` | 1 | Order of the error feedback, 0 to 2 |

The coefficients are shared by the channels. A runtime reload writes `coeff_index`, then
`coeff_value`, which auto-increments, into a shadow table; pulsing `control.commit` copies shadow
to active between beats. No sample sees mixed coefficients.

The index of a coefficient is `8·band + k`, with `k` from 0 to 4 for `b0`, `b1`, `b2`, `a1` and
`a2`. The `band_enable` bits bypass single bands while keeping their state fresh, so a re-enable
does not click. The whole block has a `bypass`, and its latency is `8·n_bands + 1` cycles.

## Dynamics {#aud-dynamics}

The dynamics processor, `LiteDSPCompressor`, implements a compressor, a limiter and an expander
or gate with one log-domain gain computer. The figure in [Dynamics](#apri-dynamics) shows its
structure.

Per beat, the side chain measures the level in the log2 domain, Q.8, either the peak or half the
log of a per-channel mean square (`detector`). A LUT-based log2 converts it. The gain computer then
applies `gr = slope_above·max(L - threshold, 0) + slope_below·max(threshold - L, 0)`, a hard knee.

| Behaviour | `slope_above` | `slope_below` |
|------------------|----------------------|----------------------|
| Compressor | `1 - 1/ratio` | 0 |
| Limiter | 1.0 | 0 |
| Expander, gate | 0 | `ratio - 1` |

The gain reduction is clamped to `gr_max` and smoothed with attack and release coefficients, Q0.16
with a Q7.24 state so that slow releases have no dead band. The `makeup` gain is added, and an
exp2 converts the log gain back to linear, up to +24 dB.

The gain multiplies the sample delayed by `lookahead` frames; the side chain sees the undelayed
sample. `stereo_link` drives all channels from the loudest channel of the previous frame with one
shared smoother. The `preset` parameter only sets reset values; every parameter is a runtime
control.

| Preset | Threshold | Ratio | Attack, release |
|---------------|-----------|---------|-------------------------|
| `compressor` | -20 dB | 4:1 | 10 ms, 100 ms |
| `limiter` | -1 dBFS | ceiling | instant, 50 ms |
| `gate` | -50 dB | 1:8 | 1 ms, 100 ms |

## Level and stereo {#aud-level}

The volume control, `LiteDSPVolume`, has a gain and a mute bit per channel. The applied gain
slews toward its target by `delta >> ramp_shift` per sample of that channel, at least one LSB, so
it converges exactly and a mute fades to exact zero. With `ramp_enable` cleared, targets apply at
once. The latency is two cycles.

The stereo matrix, `LiteDSPStereoMatrix`, computes `L' = a·L + b·R` and `R' = c·L + d·R` with
signed Q3.15 coefficients. Mid/side, panning, width, swap and mono fold-down are coefficient
presets of the driver. It accepts the L beat, then the R beat; beats out of order set the sticky
`sequence_error` and are dropped.

## Effects {#aud-effects}

The LFO, `LiteDSPLFO`, is a phase accumulator with sine, triangle, saw and square shapes and a
Q1.15 amplitude. Its handshake is the NCO's: backpressure never skips or repeats a sample. It
feeds the modulation input of the delay line or any control port.

The delay line, `LiteDSPDelayLine`, reads the sample `delay` frames back, low-pass filters it in
the feedback path with `damping`, writes back `x + feedback·filt` and outputs `dry·x + wet·d`. With
`modulation=True`, a `sink_mod` sample per frame adds `mod·mod_depth` frames to the delay, with
linear interpolation of the fraction.

The same block is the feedback comb of the reverb (wet 1, dry 0) and its Schroeder all-pass
(feedback `g`, wet 1, dry `-g`, no damping). The buffer of `max_delay` frames per channel is
rounded up to a power of two.

The wet/dry mix, `LiteDSPWetDryMix`, sums two TDM streams with signed Q1.15 gains. Both sinks are
consumed together; put a `LiteDSPStreamFIFO` on the dry branch to absorb the pipeline fill of the
wet branch, as the reverb does.

The reverb, `LiteDSPReverb`, fans the input out to parallel damped combs, sums them, passes the sum
through series all-passes and mixes it with the dry signal. Channel `c` adds `c·stereo_spread`
frames to every delay for a decorrelated stereo tail. Its controls are `room_size`, `damping`,
`allpass_gain`, `wet` and `dry`.

## Metering {#aud-metering}

The peak meter, `LiteDSPPeakMeter`, is a zero-latency tap. Per channel it keeps a peak with an
exponential fall-back of `2**decay_shift` beats per e-fold, a hold value until `clear`, and a
saturating 16-bit clip count of samples at or above `clip_threshold`. The first clip raises the
`ev.clip` event.

A shared log2 scans the peaks in turn into `peak_log2`, an unsigned Q.8 value. The host converts
it with `dBFS = 6.02·(peak_log2/256 - (data_width - 1))`.

The loudness front end, `LiteDSPLoudness`, taps the stream into a 2-band side equalizer, the
BS.1770 high shelf and RLB high-pass designed for `sample_rate`. It squares each weighted beat,
weights it by its channel's `channel_weights` entry, Q2.14, and accumulates.

After `hop_samples` frames the accumulator is latched into `sum_sq`, `hop_count` increments and
`ev.update` fires. The host builds the loudness from the hop sums: `LKFS = -0.691 +
10·log10(sum_sq/(hop_samples·2**(2·(data_width - 1))))`.

## Dither {#aud-dither}

The requantizer, `LiteDSPDither`, reduces `data_width` samples to `out_width` bits; the result stays
MSB-aligned with zero low bits. Two independent xorshift32 generators make TPDF dither of ±1
output LSB. The latency is one cycle, with no multiplier.

The `shaping` parameter builds the error feedback, per channel: `"none"`, `"ef1"` with
`v = x + e[n-1]`, or `"ef2"` with `v = x + 2e[n-1] - e[n-2]`. The error is measured against the
undithered input, so the dither noise is shaped as well. `dither_enable` and `shaping_enable` are
runtime switches.

## Host-side math and drivers {#aud-host}

`litedsp.audio.design` holds the NumPy design helpers: cookbook biquads of eight kinds
(`rbj_biquad`), Linkwitz-Riley crossovers, the BS.1770 K-weighting for any sample rate, level
and log2 conversions, `time_constant_coeff` for a time in ms, and the pan and mid/side matrices.
`litedsp.software.drivers` holds the typed drivers that speak hertz, decibels and milliseconds.

The drivers bind the registers of one block instance and convert units.

| Driver | Main methods |
|---------------------------|------------------------------------------------------------------|
| `AudioEQDriver` | `set_band`, `set_bands`, `commit`, `enable_band`, `set_bypass` |
| `CompressorDriver` | `set_threshold_db`, `set_ratio`, `set_attack_ms`, `set_release_ms`, `set_makeup_db`, `set_detector` |
| `VolumeDriver` | `set_db`, `mute`, `set_ramp` |
| `StereoMatrixDriver` | `set_matrix`, `pan`, `width`, `ms_encode`, `ms_decode`, `swap`, `mono` |
| `LFODriver` | `set_frequency` (`clk_freq` is the audio sample rate), `set_shape`, `set_amplitude` |
| `PeakMeterDriver` | `read_dbfs`, `read_peak`, `read_hold`, `clip_counts`, `clear` |
| `LoudnessDriver` | `read_hop`, `momentary`, `short_term`, `integrated` |

`AudioEQDriver.set_bands()` designs, quantizes, loads the shadow set and commits. The
`LoudnessDriver` builds momentary (400 ms), short-term (3 s) and gated integrated loudness, with
the absolute gate of -70 LKFS and the relative gate of -10 LU of BS.1770-4. Only the latest hop
sum is readable: when the host polls slower than one hop (100 ms by default), `read_hop()` appends
it once and counts the hops it missed in `hops_missed`, so poll at least once per hop.

## Verification {#aud-verification}

The block tests gate measured quality against bounds; the method is in
[Verification](#verification). The table below lists the main gates, as the tests assert them.

| Block | Test gate |
|------------------|------------------------------------------------------------------------|
| Dither | A -84 dBFS tone rounded 24 to 16 bits shows harmonics more than 10 dB above the noise; with TPDF, less than 3 dB |
| Dither shaping | `"ef2"` lowers the 0 to 0.1 fs error power by more than 6 dB against plain dither |
| EQ | Response within 0.2 dB of the float design; error feedback lowers the residual noise of a low-frequency band by more than 10 dB |
| Compressor | Static curve within 0.1 dB of the design |
| Limiter | Full-scale bursts through a 16-frame lookahead limiter peak between -1.5 and -0.7 dBFS with a -1 dBFS ceiling |
| PDM receiver | At least 45 dB SNR per channel; droop compensation within 0.5 dB |
| Loudness | Within 0.2 dB of the expected K-weighted value |

The tests are `test/test_dither.py`, `test/test_audio_eq.py`, `test/test_dynamics.py`,
`test/test_pdm.py` and `test/test_meter.py`.

## AN010: stereo audio processor {#aud-an010}

The application note assembles the family into the signal path of a small audio product: I2S in,
equalizer, dynamics, volume, metering, dither and I2S out. Every block is RTL, connected through
`tdm_layout(24, 2)` streams; the example exercises the chain in three passes. The example is
`examples/audio_processor.py`.

The figure below shows the chain. The nominal sample rate for the filter and time-constant designs
is 48 kHz.

![The AN010 target chain. An I2S slave receiver feeds a 3-band EQ, a compressor, a limiter, a
volume control and a peak meter; a dither stage reduces the samples to 16 bits for the I2S master
transmitter. The example exercises it in three passes (table below): the tone chain, the dynamics
chain and the I2S transport.](aud_an010.svg)

Feeding the processing chain through the I2S converters would multiply the simulated cycles by
the BCLK divider and the slot length, so the example runs the chain in three short passes, which
share the blocks and carry only the frames each gate needs.

| Pass | Blocks | Stimulus | Gate |
|-----------------|-------------------------------|-------------------------------------------|-------------------------------|
| 1, tone chain | EQ, volume, peak meter, dither | A: 250, 500, 1000, 3000 and 8000 Hz at -20 dBFS; D: 250 Hz at -6 dBFS, EQ bypassed | A: within 0.3 dB of the design; D: in-band THD+N of the 16-bit output at most -80 dB |
| 2, dynamics | Compressor, limiter, peak meter | B: 1 kHz at -30, -20, -10, -3 dBFS; C: 1 kHz at 0 dBFS through the limiter | B: within 1 dB of the static curve and 0.1 dB of the model; C: peak at most -0.5 dBFS, no clip |
| 3, transport | I2S TX, pins, I2S RX, dither, I2S TX, pins, I2S RX | 48 random 24-bit frames, BCLK = `sys/4` | Received 16-bit words equal the rounded stimulus from the first frame after the receivers lock on LRCK |

The EQ of pass A has a low shelf at 80 Hz +6 dB, a peak at 1 kHz -4 dB with Q 1.5 and a high shelf
at 8 kHz +3 dB. The THD+N band of pass D is 20 Hz to 10 kHz.

The compressor of pass B uses a peak detector, -20 dB threshold, 4:1 ratio, instant attack and 10 ms
release, over 128 frames per level. The limiter of pass C has a -1 dBFS ceiling, instant attack and
32 frames of lookahead.

The dynamics segments are separated by silence gaps. Bypass bits change in the middle of a gap, so
the pipeline, up to the limiter's 32 frames of lookahead, only carries silence while a control
changes; the gaps also locate the segments at the output.

The two tone-chain measurements start from reset, because the 80 Hz shelf rings for about 100
frames and would leak between segments; the THD+N measurement bypasses the EQ for the same
reason.

### Running it {#aud-an010-run}

```sh
python3 examples/audio_processor.py
python3 examples/audio_processor.py --plot-dir <dir>
```

The output below is the run of the first command (Migen simulation):

```console
$ python3 examples/audio_processor.py
pass 1a (tone chain, EQ): 352 frames
EQ    250 Hz +0.01 dB (design -0.06)  500 Hz -0.86 dB (design -0.67)  1000 Hz -4.07 dB (design -4.00)  3000 Hz -0.15 dB (design -0.19)  8000 Hz +1.47 dB (design +1.48)  -> max error 0.20 dB (limit 0.3)
pass 1b (tone chain, THD+N): 224 frames
THD+N -95.0 dB in 20 Hz..10 kHz (-79.6 dB full band: the 2nd-order shaper moves the dither noise above the audio band), -6 dBFS 250 Hz at the 16-bit output (limit -80.0)
pass 2 (dynamics chain): 784 frames
COMP  -30 -> -30.00 dBFS (design -30.00, model -30.00)  -20 -> -20.00 dBFS (design -20.00, model -20.00)  -10 -> -17.40 dBFS (design -17.50, model -17.40)  -3 -> -15.63 dBFS (design -15.75, model -15.63)  -> max error 0.12 dB vs design (limit 1.0), 0.000 dB vs model (limit 0.1)
LIM   0 dBFS in -> peak -0.96 dBFS (model -0.96, ceiling -1.0 +0.5), clip count 0
pass 3 (I2S transport): 48 frames
I2S   49 words received, transport bit-exact (stimulus frame 1 onwards)
PASS
```

### Results {#aud-an010-results}

The figure below is the plot the example writes: the EQ magnitude against the design, the
compressor static curve and the spectrum of the 16-bit output.

![AN010 results (simulation): EQ magnitude against the design (left), compressor static curve
(middle), 16-bit output spectrum (right), from `examples/audio_processor.py
--plot-dir`.](aud_an010_audio.png)

The largest EQ error, 0.2 dB at 500 Hz, comes from the 4 ms analysis window, with 250 Hz bins and
the shelf's settling tail, and from the Q4.28 coefficient quantization. It stays below the 0.3 dB
gate.

The compressor output equals the bit-exact model to the printed precision. Against the design line
`out = in - (in - threshold)·(1 - 1/ratio)`, it sits about 0.1 dB high at the compressed levels:
with an instant attack and a 10 ms release, the gain reduction dips slightly between the peaks of
the sine.

The limiter's lookahead lets its instant attack act before the peak: -0.96 dBFS, no clip.
The full-band THD+N of the 16-bit output, -79.6 dB, is the price of the second-order noise shaper,
whose total noise power is higher than plain TPDF dither; in band it reads -95.0 dB.

### Toward a hardware design {#aud-an010-hw}

The registers of the chain are the block registers, and the drivers of [Host-side math and
drivers](#aud-host) speak the units used above. The standalone core `examples/audio_core.yml`
generates the EQ, compressor, volume and dither part ([Standalone cores](#apps-cores)); the I2S
converters have pins rather than stream ports, so they sit next to the core. The clock budget of
the serial engines is in [Two engine styles](#aud-engines).

The note keeps two simplifications: the compressor of pass B uses an instant attack and a 10 ms
release, so that each level settles inside its 128 frames (the preset defaults are 10 ms and
100 ms), and both channels carry the same signal. The stereo matrix, the reverb and the PDM
converters are not in this chain; their block tests and datasheets cover them.

Where to go next: [Radar and sonar primer](#radar-primer) for the next family, [Using the
application families](#apps-using) for the standalone audio core.
