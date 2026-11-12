# Glossary {#glossary}

The terms of signal processing and of LiteDSP used in this manual, in alphabetical order. Each
entry points to the section that explains it.

| Term | Meaning |
|--------------------|--------------------------------------------------------------------------------|
| Aliasing | Folding of a frequency above fs/2 onto a lower one by sampling. See [Sampling and the Nyquist limit](#pri-sampling) |
| Alpha-beta filter | Tracker update with fixed position and velocity gains. See [Tracking](#rpri-tracking) |
| Analytic signal | Complex signal without negative frequencies, made from a real one. See [Hilbert transformer](#pri-hilbert) |
| Angle tracker | Type-II loop that smooths an angle stream and estimates the speed. See [Position and speed](#mot-position) |
| Anti-windup | Stops a PI integrator from accumulating while the output is clamped. See [PI regulators and anti-windup](#mpri-pi) |
| Arbitrary resampler | Rate change by any ratio, by interpolation at fractional positions. See [Rational and arbitrary resampling](#pri-resampling) |
| Back-EMF | Voltage a turning motor induces in its windings, proportional to the speed. See [Torque, current and back-EMF](#mpri-torque) |
| Backpressure | A consumer holding `ready` low, which stops the producer. See [Backpressure](#pri-backpressure) |
| Bayer mosaic | Colour filter pattern of a sensor, one colour per photosite (RGGB and its phases). See [Colour sensors and demosaicing](#ipri-bayer) |
| BCLK | Bit clock of a serial audio link. See [Serial audio links](#apri-i2s) |
| Beat | One stream transfer: one clock cycle with `valid` and `ready` high. See [The valid/ready handshake](#pri-handshake) |
| Biquad | Second-order IIR section, two poles and two zeros. See [IIR filters and biquads](#pri-iir) |
| Bit reversal | Output order of a decimation-in-frequency FFT. See [Bit reversal](#pri-bitrev) |
| Blind speed | Target velocity an MTI canceller cancels like clutter. See [Clutter and MTI](#rpri-mti) |
| Block | One registry entry, a `LiteDSP*` class with its datasheet. See [Block contract](#architecture) |
| Block floating point | FFT scaling with one exponent per frame (`scaling="bfp"`). See [The FFT](#pri-fft) |
| Budget | Recorded implementation or characterization result checked by CI. See [Performance](#performance) |
| Butterfly | Sum, difference and twiddle product of two FFT values. See [The FFT](#pri-fft) |
| Bypass | Run-time control passing the input unchanged, delay-matched on the blocks built with `add_bypass`. See [Bypass](#pri-bypass) |
| Cell | Non-negative range-Doppler value with its threshold and decision (`cell_layout`). See [Stream kinds and framing](#rad-streams) |
| CFAR | Constant false alarm rate detection: threshold scaled from the local noise. See [Detection and CFAR](#rpri-cfar) |
| Chain | Blocks connected by streams, in a SoC or from a netlist. See [Block contract](#architecture) |
| CIC | Cascaded integrator-comb filter: multiplier-free rate change. See [CIC filters](#pri-cic) |
| Clarke transform | Maps three phase values onto the stationary α/β plane. See [Reference frames](#mpri-frames) |
| Clutter map | Detector that compares each cell with its own average across scans. See [Detection and CFAR](#rpri-cfar) |
| Co-simulation | Verilator run of the generated Verilog against the golden model. See [Verification](#verification) |
| Coefficient | Weight of a filter tap. See [FIR filters](#pri-fir) |
| Comb | Difference x[n] - x[n-M], the second half of a CIC. See [CIC filters](#pri-cic) |
| Complex baseband | Signal carried as I/Q pairs, band from -fs/2 to +fs/2. See [Real and complex baseband](#pri-iq) |
| Composite | Block built from other blocks, such as the DDC. See [Block contract](#architecture) |
| CORDIC | Shift-and-add vector rotation: sin, cos, magnitude, phase. See [CORDIC](#pri-cordic) |
| Corner turn | Reorder of a CPI from pulses (fast time) to range-bin columns (slow time). See [Fast time and slow time](#rpri-matrix) |
| CPI | Coherent processing interval: the M pulses processed together. See [Pulses, PRI and CPI](#rpri-timing) |
| dBFS | Level relative to the full scale of the format. See [Measuring a signal](#pri-metrics) |
| DC blocker | High-pass filter removing the constant part of a signal. See [Moving average and DC blocker](#pri-small-filters) |
| DDC | Digital down-converter: NCO, mixer and decimator. See [DDC and DUC](#pri-ddc) |
| DDS | Direct digital synthesizer, another name for the NCO. See [The NCO](#pri-nco) |
| Dead time | Interval with both transistors of a half-bridge off at every switching edge. See [The machine and the inverter](#mpri-machine) |
| Decimation | Lowering the sample rate by an integer, after filtering. See [Decimation](#pri-decimation) |
| Delay balancing | Delaying the shorter branch of a join to align samples. See [Delay balancing](#pri-delay-balance) |
| Demosaicing | Interpolation of the two missing colours of each Bayer pixel. See [Colour sensors and demosaicing](#ipri-bayer) |
| DF2T | Transposed direct form II, the biquad form of `LiteDSPIIRBiquad`. See [IIR filters and biquads](#pri-iir) |
| DFT | Discrete Fourier transform: N samples to N frequency bins. See [The discrete Fourier transform](#pri-dft) |
| Dither | Small random signal added before requantization; TPDF in LiteDSP. See [Dither and noise shaping](#apri-dither) |
| DUC | Digital up-converter: interpolator, mixer and NCO. See [DDC and DUC](#pri-ddc) |
| Elastic pipeline | Pipeline whose history advances only on real input transfers. See [Elastic pipelines](#pri-elastic) |
| ENOB | Effective number of bits: (SINAD - 1.76) / 6.02. See [Measuring a signal](#pri-metrics) |
| eol | Stream tag on the last pixel of every line. See [Pixels, lines and frames](#ipri-raster) |
| Error feedback | Feeding the rounding error back into the next sum to shape it. See [IIR filters and biquads](#pri-iir) |
| Family | A registry category and its package directory, such as filter. See [Block contract](#architecture) |
| Farrow structure | Polynomial interpolator with a run-time fractional position. See [Fractional delay and the Farrow structure](#pri-farrow) |
| Fast time | Sample order within one pulse, range bin after range bin. See [Fast time and slow time](#rpri-matrix) |
| FFT | Fast Fourier transform. See [The FFT](#pri-fft) |
| FIR | Finite impulse response filter: weighted sum of the last N inputs. See [FIR filters](#pri-fir) |
| Fixed point | Integer arithmetic with an implied binary point. See [Fixed-point numbers](#pri-qformat) |
| FOC | Field-oriented control: regulation of the d and q currents in the rotor frame. See [Field-oriented control](#mpri-foc) |
| Folded architecture | Option reusing one datapath over several cycles per sample. See [Sample rate, clock rate and lanes](#pri-rates) |
| Frame | Group of beats delimited by `first` and `last`. See [Frames](#pri-framing) |
| Gate floor | Lowest fmax CI accepts for a configuration (`fmax_min`). See [Performance](#performance) |
| Goertzel | Single-bin DFT by a second-order resonator. See [Goertzel](#pri-goertzel) |
| Golden model | NumPy reference of a block in `test/models.py`. See [Verification](#verification) |
| Group delay | Delay of a signal envelope through a filter, in samples. See [What a filter does](#pri-filter-basics) |
| Half-band filter | Low-pass at 0.25 with every other tap zero, for rate change by 2. See [Half-band filters](#pri-halfband) |
| Hilbert transformer | Filter shifting positive frequencies by -90 degrees. See [Hilbert transformer](#pri-hilbert) |
| I/Q | In-phase and quadrature parts of a complex sample, I + jQ. See [Real and complex baseband](#pri-iq) |
| I2S | Three-wire serial audio link and its frame format. See [Serial audio links](#apri-i2s) |
| IIR | Infinite impulse response filter, with output feedback. See [IIR filters and biquads](#pri-iir) |
| Image | Copy of a band created by zero insertion or real mixing. See [Interpolation](#pri-interpolation) |
| Integrator | Running sum, the first half of a CIC decimator. See [CIC filters](#pri-cic) |
| Interpolation | Raising the sample rate by an integer, then filtering. See [Interpolation](#pri-interpolation) |
| K-weighting | BS.1770 filter, a high shelf and a high-pass, applied before the loudness sum. See [Metering and loudness](#apri-metering) |
| Kernel | Coefficients of a neighbourhood operation, summed over a window. See [Neighbourhood operations](#ipri-kernel) |
| Lane | One sample of a parallel beat (`n_samples` lanes per beat). See [Sample rate, clock rate and lanes](#pri-rates) |
| Latency | Delay of a block in samples, its `latency` attribute. See [Latency in samples](#pri-latency) |
| Leakage | Spreading of a tone over all FFT bins. See [Windows and leakage](#pri-window) |
| Line buffer | Memory of the previous lines that forms K x K windows from a raster stream. See [The line buffer](#img-linebuffer) |
| Linear phase | Same delay for every frequency, from symmetric taps. See [Linear phase and symmetry](#pri-linear-phase) |
| LKFS | Loudness unit of BS.1770, K-weighted, relative to full scale. See [Metering and loudness](#apri-metering) |
| LO | Local oscillator: the NCO feeding a mixer. See [Complex mixing](#pri-mixing) |
| Lookahead | Main-path delay that lets a limiter act before a peak. See [Dynamics](#apri-dynamics) |
| LRCK | Word clock of a serial audio link; selects the slot. See [Serial audio links](#apri-i2s) |
| LSB | Least significant bit; the step 2^-n of a Qm.n format. See [Fixed-point numbers](#pri-qformat) |
| MAC | Multiply-accumulate unit, time-shared over the taps. See [Polyphase filters](#pri-polyphase) |
| Matched filter | Correlation with the conjugate, time-reversed transmitted pulse. See [Pulse compression](#rpri-compression) |
| Mixer | Complex multiplier shifting a spectrum in frequency. See [Complex mixing](#pri-mixing) |
| Monopulse | Angle measurement from the phase difference of two half-arrays. See [Arrays and angle](#rpri-arrays) |
| Moving average | Mean of the last L samples, by a running sum. See [Moving average and DC blocker](#pri-small-filters) |
| MTI | Moving target indicator: pulse-to-pulse canceller that removes stationary clutter. See [Clutter and MTI](#rpri-mti) |
| NCO | Numerically controlled oscillator: phase accumulator and tables. See [The NCO](#pri-nco) |
| Netlist | JSON description of a chain read by the flow. See [Flow, generator, GUI and host software](#tooling) |
| Noise shaping | Error feedback that moves quantization noise out of a band. See [Dither and noise shaping](#apri-dither) |
| Normalized frequency | Frequency in cycles per sample, 0.5 being fs/2. See [Sampling and the Nyquist limit](#pri-sampling) |
| Nyquist frequency | Half the sample rate, the highest representable frequency. See [Sampling and the Nyquist limit](#pri-sampling) |
| Parallel variant | N samples per clock version of a block, bit-identical. See [Sample rate, clock rate and lanes](#pri-rates) |
| Param | Per-frame stream field next to the payload, such as a timestamp. See [Frames](#pri-framing) |
| Park transform | Rotation of the α/β vector by the rotor angle into the d/q frame. See [Reference frames](#mpri-frames) |
| Passband | Frequencies a filter keeps. See [What a filter does](#pri-filter-basics) |
| PDM | Pulse-density modulation: a 1-bit stream whose density of ones follows the signal. See [PDM microphones](#apri-pdm) |
| Per-unit | Quantities divided by base values so they sit around 1.0. See [Per-unit scaling](#mpri-per-unit) |
| Phase accumulator | Register adding the phase increment on every sample. See [The NCO](#pri-nco) |
| Phase increment | NCO frequency word, `phase_inc`. See [The NCO](#pri-nco) |
| PMSM | Permanent-magnet synchronous motor. See [The machine and the inverter](#mpri-machine) |
| Polyphase | Filter split into R sub-filters running at the low rate. See [Polyphase filters](#pri-polyphase) |
| PRI, PRF | Pulse repetition interval and its inverse, the pulse repetition frequency. See [Pulses, PRI and CPI](#rpri-timing) |
| PSD | Power spectral density: averaged power spectrum. See [Power spectral density and Welch](#pri-psd) |
| PSLR | Peak-to-sidelobe ratio of a compressed pulse. See [Pulse compression](#rpri-compression) |
| PWM | Pulse-width modulation; centre-aligned in LiteDSP. See [Centre-aligned PWM](#mpri-pwm) |
| Qm.n | Signed format with m integer bits (sign included) and n fractional bits. See [Fixed-point numbers](#pri-qformat) |
| Quarter-wave table | One quarter of a sine period, the rest by symmetry. See [The NCO](#pri-nco) |
| Range bin | Range interval of one sample, `c / (2 fs)`. See [Echoes and range](#rpri-range) |
| Range-Doppler map | Cells of all range bins by Doppler bins for one CPI. See [Doppler processing](#rpri-doppler) |
| Rank filter | Window sort that outputs one rank: erosion, median or dilation. See [Neighbourhood operations](#ipri-kernel) |
| Rational resampler | Rate change by L/M: interpolation by L, decimation by M. See [Rational and arbitrary resampling](#pri-resampling) |
| Register | Control or status register of a block on the CSR bus. See [Registers](#registers) |
| Registry | List of all blocks with their reflected metadata. See [Block contract](#architecture) |
| Rounding | Removing low bits to the nearest value (half up in LiteDSP). See [Rounding and saturation](#pri-rescale) |
| Sample | One value of the signal: one real value or one I/Q pair. See [Sampling and the Nyquist limit](#pri-sampling) |
| Sample rate | Samples per second of a signal, fs. See [Sample rate, clock rate and lanes](#pri-rates) |
| Saturation | Clamping a value to the range of the format. See [Rounding and saturation](#pri-rescale) |
| SDF | Single-path delay-feedback: streaming FFT architecture. See [The FFT](#pri-fft) |
| SFDR | Spurious-free dynamic range: signal over the largest spur. See [Measuring a signal](#pri-metrics) |
| Shadow table | Register set written by the host and committed to the active set at a frame start. See [Geometry, codes and tables](#img-rules) |
| SINAD | Signal over noise and distortion. See [Measuring a signal](#pri-metrics) |
| Sliding-mode observer | Sensorless back-EMF estimator driven by a switching term. See [Rotor position sensors](#mpri-sensors) |
| Slow time | One range bin seen across the pulses of a CPI. See [Fast time and slow time](#rpri-matrix) |
| SNR | Signal-to-noise ratio. See [Measuring a signal](#pri-metrics) |
| SOS | Second-order sections: an IIR filter as a cascade of biquads. See [IIR filters and biquads](#pri-iir) |
| Spur | Discrete unwanted line in a spectrum. See [Phase truncation and spurs](#pri-nco-spurs) |
| Standalone core | Verilog core written by `litedsp_gen` from a YAML file. See [Flow, generator, GUI and host software](#tooling) |
| Stopband | Frequencies a filter removes. See [What a filter does](#pri-filter-basics) |
| Stream | LiteX endpoint carrying samples with `valid` and `ready`. See [The valid/ready handshake](#pri-handshake) |
| SVPWM | Space-vector modulation: min/max zero-sequence injection. See [Modulation](#mpri-svpwm) |
| Tap | One coefficient and its product in a FIR filter. See [FIR filters](#pri-fir) |
| Target burst | Per-CPI target records closed by a terminator beat holding the count. See [Stream kinds and framing](#rad-streams) |
| TDM stream | Channel-tagged audio stream, one sample per beat. See [Channels on one stream](#apri-channels) |
| Truncation | Removing low bits by a plain shift, rounding toward minus infinity. See [Rounding and saturation](#pri-rescale) |
| TVG | Time-varying gain: sonar gain rising with range to compensate the losses. See [Sonar and time-varying gain](#rpri-sonar) |
| Twiddle factor | Complex exponential multiplying an FFT butterfly difference. See [The FFT](#pri-fft) |
| Welch method | PSD averaging windowed, overlapping frames. See [Power spectral density and Welch](#pri-psd) |
| Window | Taper applied to a frame before the FFT. See [Windows and leakage](#pri-window) |
| Word growth | Extra bits a product or a sum needs. See [Word growth](#pri-growth) |
| Wrap | Overflow keeping only the low bits of a value. See [Rounding and saturation](#pri-rescale) |
| YCbCr | Luma and two colour differences, from RGB by a 3 x 3 matrix. See [Colour spaces](#ipri-colour) |
| Zipper noise | Clicks from a gain changed in one step; avoided by ramping. See [Level, panning and mid/side](#apri-level) |
