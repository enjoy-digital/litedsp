# LiteDSP Block Catalog

229 blocks, generated from the block registry by `litedsp/flow/docgen.py` (do not edit by hand — regenerate with `python3 -m litedsp.flow.docgen`).

## Signal Generation (`generation/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [NCO (DDS)](nco.md) | `LiteDSPNCO` | 1 | 0 | Numerically-Controlled Oscillator (a.k.a. DDS). |
| [CORDIC (rotate)](cordic_rot.md) | `LiteDSPCORDIC` | 19 | 2 | Pipelined CORDIC (one iteration per stage), gain-compensated, full-circle. |
| [CORDIC (vector)](cordic_vec.md) | `LiteDSPCORDIC` | 19 | 1 | Pipelined CORDIC (one iteration per stage), gain-compensated, full-circle. |
| [Chirp (LFM)](chirp.md) | `LiteDSPChirp` | var | — | Linear-FM (chirp) I/Q generator: the instantaneous frequency ramps by ``rate`` per sample. |
| [Noise (AWGN)](noise_source.md) | `LiteDSPNoiseSource` | var | — | Approximate-Gaussian (AWGN) complex noise via summed xorshift32 streams (CLT). |
| [Pattern source](pattern_source.md) | `LiteDSPPatternSource` | var | 0 | I/Q test-pattern generator (constant / counter ramp / PRBS / impulse). |

## Mixing / Frequency Translation (`mixing/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Mixer (complex)](mixer.md) | `LiteDSPMixer` | 2 | 4 | Complex mixer with runtime up/down mode and bypass. |
| [DDC](ddc.md) | `LiteDSPDDC` | 1 | 6 | Digital down-converter: NCO + complex mixer (down) + decimator. |
| [DUC](duc.md) | `LiteDSPDUC` | 1 | 6 | Digital up-converter: interpolator + complex mixer (up) + NCO. |
| [Channelizer](channelizer.md) | `LiteDSPChannelizer` | 34 | 24 | Split a wide band into ``n_channels`` uniformly-spaced sub-channels. |
| [PFB channelizer (scalable)](pfb_channelizer.md) | `LiteDSPPFBChannelizer` | 60 | 11 | Uniform filter bank (polyphase FIR + scalable direct/FFT transform). |

## Filtering (`filter/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Bitstream (sigma-delta/PDM) decimator](bitstream_decimator.md) | `LiteDSPBitstreamDecimator` | 1 | 0 | 1-bit sigma-delta / PDM bitstream -> PCM samples through a runtime-rate sinc^N decimator. |
| [FIR (real)](fir_real.md) | `LiteDSPFIRFilter` | 3 | — | Pipelined single-rate real FIR filter with stream I/O and round+saturate output. |
| [FIR (complex)](fir_complex.md) | `LiteDSPFIRFilterComplex` | 3 | 2 | Complex FIR: identical real FIRs on I and Q, shared coefficients, with bypass + CSR. |
| [FIR decimator](fir_decimator.md) | `LiteDSPFIRDecimator` | 33 | 2 | Decimate-by-R complex FIR with a single time-shared MAC per I/Q. |
| [FIR interpolator](fir_interpolator.md) | `LiteDSPFIRInterpolator` | 32 | 2 | Interpolate-by-L complex FIR with a single time-shared MAC per I/Q (polyphase). |
| [CIC decimator](cic_decimator.md) | `LiteDSPCICDecimator` | 1 | 0 | CIC decimator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N``, rescaled to width. |
| [CIC interpolator](cic_interpolator.md) | `LiteDSPCICInterpolator` | 1 | 0 | CIC interpolator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N / R``, rescaled. |
| [Halfband decimator](halfband_dec.md) | `LiteDSPHalfbandDecimator` | 24 | — | Decimate-by-2 half-band FIR with structural zero-tap pruning. |
| [Halfband interpolator](halfband_int.md) | `LiteDSPHalfbandInterpolator` | 23 | — | Interpolate-by-2 half-band FIR with structural zero-tap pruning. |
| [Hilbert](hilbert.md) | `LiteDSPHilbert` | 3 | — | Real -> analytic (complex) signal via a Hilbert FIR. |
| [IIR biquad](iir_biquad.md) | `LiteDSPIIRBiquad` | 2 | 24 | One DF2T biquad section applied to I and Q with shared coefficients. |
| [DC blocker](dc_blocker.md) | `LiteDSPDCBlocker` | 1 | 0 | Multiplier-free 1st-order DC-removal IIR (per I/Q). |
| [DC blocker (mono)](dc_blocker_real.md) | `LiteDSPDCBlocker` | 1 | 0 | Multiplier-free 1st-order DC-removal IIR (per I/Q). |
| [Moving average](moving_average.md) | `LiteDSPMovingAverage` | 1 | 0 | Boxcar moving average over ``2**length_log2`` samples (per I/Q), a.k.a. CIC-1. |
| [Farrow interpolator](farrow.md) | `LiteDSPFarrowInterpolator` | 7 | 16 | Cubic (Catmull-Rom) Farrow fractional-delay interpolator with runtime ``mu``. |
| [LMS equalizer](equalizer.md) | `LiteDSPLMSEqualizer` | 1 | — | Adaptive complex FIR equalizer: trained LMS, blind CMA or decision-directed. |
| [Notch](notch.md) | `LiteDSPNotch` | 1 | — | Tunable 2nd-order notch (zeros on the unit circle, poles at radius ``r``). |
| [Comb filter](comb_filter.md) | `LiteDSPCombFilter` | 1 | — | Feed-forward comb ``y[n] = x[n] - x[n-D]`` (nulls at multiples of fs/D), per I/Q. |
| [Allpass](allpass.md) | `LiteDSPAllpass` | 1 | — | 1st-order allpass ``y[n] = -a*x[n] + x[n-1] + a*y[n-1]`` (flat magnitude), per I/Q. |
| [Pulse shaper (RRC)](pulse_shaper.md) | `LiteDSPPulseShaper` | 33 | — | Root-raised-cosine pulse-shaping interpolator (``sps`` samples/symbol). |
| [Rational resampler](rational_resampler.md) | `LiteDSPRationalResampler` | var | — | Resample by ``L/M``: polyphase interpolate-by-L then decimate-by-M. |
| [Arbitrary resampler](arb_resampler.md) | `LiteDSPArbResampler` | var | — | Arbitrary (non-rational) sample-rate conversion via cubic Farrow + a phase accumulator. |

## Rate Conversion (`rate/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Decimator](decimator.md) | `LiteDSPDecimator` | 1 | — | Integer decimator: anti-alias filter + rate drop. |
| [Interpolator](interpolator.md) | `LiteDSPInterpolator` | 1 | — | Integer interpolator: rate expand + anti-image filter. |
| [Downsampler](downsampler.md) | `LiteDSPDownsampler` | 1 | — | Keep one of every ``factor`` I/Q samples (naive decimation, no anti-alias filter). |
| [Upsampler](upsampler.md) | `LiteDSPUpsampler` | 1 | — | Emit ``factor`` I/Q samples per input: sample-and-hold (default) or zero-stuff. |
| [Resampler farm](resampler_farm.md) | `LiteDSPResamplerFarm` | 32 | 2 | Decimate-by-R complex FIR for ``n_channels`` streams sharing one serial-MAC engine. |

## Level Control / Measurement (`level/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Gain](gain.md) | `LiteDSPGain` | 1 | 2 | Runtime-configurable gain for a complex I/Q stream, with bypass and saturation. |
| [Power meter](power.md) | `LiteDSPPower` | var | 2 | Average power meter: passes the I/Q stream through and measures mean ``I**2 + Q**2``. |
| [AGC](agc.md) | `LiteDSPAGC` | 1 | 4 | Automatic gain control: drives |output| toward ``target``. |
| [DPD actuator](dpd.md) | `LiteDSPDPD` | 4 | 12 | Memory-polynomial-lite (GMP-lite) digital predistortion actuator. |
| [Saturate](saturate.md) | `LiteDSPSaturate` | 1 | 0 | Rescale a complex I/Q stream by a fixed right ``shift`` with round-half-up + saturation. |
| [CFR (peak cancellation)](cfr.md) | `LiteDSPCFR` | 1 | 5 | Crest-factor reduction by peak cancellation: subtract a scaled low-pass pulse per peak. |
| [Clipper](clipper.md) | `LiteDSPClipper` | 1 | — | Hard limiter: clamp each of I/Q to +/- ``threshold`` (runtime). ``clip`` flags a clip. |
| [RMS](rms.md) | `LiteDSPRMS` | var | 2 | RMS magnitude over ``2**window_log2`` samples: ``sqrt(mean(I**2 + Q**2))``. |
| [Squelch](squelch.md) | `LiteDSPSquelch` | 1 | — | Mute the I/Q stream when instantaneous power ``I**2 + Q**2`` is below threshold. |
| [Envelope detector](envelope.md) | `LiteDSPEnvelopeDetector` | 2 | — | Envelope follower on |I+jQ| with separate attack/release time constants. |
| [Log2](log2.md) | `LiteDSPLog2` | 1 | — | Fixed-point base-2 logarithm of an unsigned input (priority-encoder + mantissa). |
| [Log power (dB)](log_power.md) | `LiteDSPLogPower` | 2 | — | Power-to-dB: ``10*log10(x) = 3.0103 * log2(x)`` (x is a power value, unsigned). |
| [Exp2 (antilog)](exp2.md) | `LiteDSPExp2` | 2 | 0 | Fixed-point ``2**v`` of a signed log2-domain value (ROM mantissa + integer shift). |

## Impairment Correction (`correction/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [DC offset](dc_offset.md) | `LiteDSPDCOffset` | 1 | — | Estimate and remove a DC offset per I/Q with a leaky-integrator mean. |
| [I/Q balance](iq_balance.md) | `LiteDSPIQBalance` | 1 | — | Correct I/Q gain & phase imbalance with a 2x2 matrix, plus an estimator for calibration. |
| [Derotator (CFO)](derotator.md) | `LiteDSPDerotator` | 2 | — | Frequency-shift (derotate) an I/Q stream by ``-phase_inc`` (NCO + down-mixer). |

## Communications (`comm/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [FM demod](fm_demod.md) | `LiteDSPFMDemod` | 19 | 4 | FM discriminator: instantaneous frequency = ``angle(x[n] * conj(x[n-1]))``. |
| [AM demod](am_demod.md) | `LiteDSPAMDemod` | 2 | — | AM envelope demodulator: ``|x|`` (magnitude) with the carrier DC removed. |
| [Slicer](slicer.md) | `LiteDSPSlicer` | 1 | — | Hard-decision QAM slicer: map each of I/Q to the nearest PAM level. |
| [Soft demapper (LLR)](soft_demapper.md) | `LiteDSPSoftDemapper` | 2 | 2 | Gray-coded square-QAM max-log soft demapper: per-axis folded piecewise-linear LLRs. |
| [Symbol mapper](symbol_mapper.md) | `LiteDSPSymbolMapper` | 1 | — | Map a QAM symbol index to a constellation I/Q point (inverse of :class:`LiteDSPSlicer`). |
| [Correlator](correlator.md) | `LiteDSPCorrelator` | 3 | 14 | Sliding correlation of the I/Q stream against a known real ``sequence``. |
| [Frame sync (preamble)](frame_sync.md) | `LiteDSPFrameSync` | 9 | 23 | Preamble detector + stream aligner: the gateway block for burst receivers. |
| [Timing recovery (M&M)](timing_recovery.md) | `LiteDSPTimingRecovery` | var | 18 | Symbol timing recovery with an interpolation controller (M&M or Gardner detector). |
| [Carrier loop (PLL)](carrier_loop.md) | `LiteDSPCarrierLoop` | 1 | — | Carrier recovery: derotate the input with an internal NCO driven by a PI loop. |
| [Phase detector](phase_detect.md) | `LiteDSPPhaseDetect` | 19 | — | Instantaneous phase ``atan2(Q, I)`` of an I/Q stream (CORDIC vectoring). |
| [CFO estimator (coarse)](cfo_estimator.md) | `LiteDSPCFOEstimator` | 0 | 4 | Coarse CFO estimator: delay-conjugate-multiply autocorrelation + CORDIC angle. |
| [Differential encoder](diff_encoder.md) | `LiteDSPDifferentialEncoder` | 1 | — | ``out[n] = (in[n] + out[n-1]) mod M`` (symbol indices). |
| [Differential decoder](diff_decoder.md) | `LiteDSPDifferentialDecoder` | 1 | — | ``out[n] = (in[n] - in[n-1]) mod M`` (inverse of the encoder). |
| [Scrambler (LFSR)](scrambler.md) | `LiteDSPScrambler` | 1 | — | Self-synchronizing multiplicative scrambler ``y = x ^ y[-t1] ^ y[-t2] ...`` (bit-serial). |
| [Descrambler (LFSR)](descrambler.md) | `LiteDSPDescrambler` | 1 | — | Inverse of :class:`LiteDSPScrambler` ``x = y ^ y[-t1] ^ y[-t2] ...`` (self-synchronizing). |
| [CRC](crc.md) | `LiteDSPCRC` | 1 | — | Bit-serial MSB-first CRC; passes ``data`` through and updates the ``crc`` register. |
| [Convolutional encoder](conv_encoder.md) | `LiteDSPConvEncoder` | 1 | — | Rate-1/2 convolutional encoder (default K=7, G=[0o171, 0o133]). |
| [Viterbi decoder](viterbi_decoder.md) | `LiteDSPViterbiDecoder` | 1 | 0 | Hard/soft-decision Viterbi decoder (rate 1/n, selectable survivor architecture). |
| [Puncturer](puncturer.md) | `LiteDSPPuncturer` | var | 0 | TX puncturer: drops coded bits of the rate-1/n stream per the puncturing matrix. |
| [Depuncturer (LLR)](depuncturer.md) | `LiteDSPDepuncturer` | var | 0 | RX depuncturer: reassembles full soft symbols, reinserting erasures (LLR 0) per pattern. |
| [Block interleaver](block_interleaver.md) | `LiteDSPBlockInterleaver` | var | 0 | TX block interleaver: rows x cols symbols in row-wise, out column-wise. |
| [Block deinterleaver](block_deinterleaver.md) | `LiteDSPBlockDeinterleaver` | var | 0 | RX block deinterleaver: the exact inverse of :class:`LiteDSPBlockInterleaver`. |
| [RS encoder (255,k)](rs_encoder.md) | `LiteDSPRSEncoder` | var | 0 | Systematic RS(255, k) encoder: k message bytes in, n = 255 codeword bytes out. |
| [RS decoder (255,k)](rs_decoder.md) | `LiteDSPRSDecoder` | var | 0 | RS(255, k) decoder: n = 255 codeword bytes in, k corrected message bytes out. |
| [CCSDS RS encoder](ccsds_rs_encoder.md) | `LiteDSPCCSDSRSEncoder` | var | 0 | CCSDS 131.0-B-5 RS(255,223) encoder with dual-basis stream symbols. |
| [CCSDS RS decoder](ccsds_rs_decoder.md) | `LiteDSPCCSDSRSDecoder` | var | 0 | CCSDS 131.0-B-5 RS(255,223) decoder with dual-basis stream symbols. |
| [LDPC encoder (802.11n)](ldpc_encoder.md) | `LiteDSPLDPCEncoder` | var | 0 | 802.11n rate-1/2 (648, 324) LDPC encoder: 324 message bits in, 648 codeword bits out. |
| [LDPC decoder (802.11n)](ldpc_decoder.md) | `LiteDSPLDPCDecoder` | var | 0 | 802.11n rate-1/2 (648, 324) LDPC decoder: 648 LLRs in, 324 corrected bits out. |
| [LDPC decoder (z-parallel)](ldpc_decoder_z_parallel.md) | `LiteDSPLDPCDecoderZParallel` | var | 0 | Foldable lift-parallel normalized min-sum LDPC decoder. |
| [OFDM CP insert](cp_insert.md) | `LiteDSPCPInsert` | var | — | Insert a cyclic prefix: N-sample symbols in, (CP + N)-sample symbols out. |
| [OFDM CP remove](cp_remove.md) | `LiteDSPCPRemove` | 0 | — | Remove a cyclic prefix: (CP + N)-sample symbols in, framed N-sample symbols out. |
| [OFDM equalizer (1-tap)](ofdm_equalizer.md) | `LiteDSPOFDMEqualizer` | 2 | 6 | LS channel estimation + divider-free one-tap OFDM equalizer with per-bin CSI. |
| [FM modulator](fm_modulator.md) | `LiteDSPFrequencyModulator` | 2 | 2 | FM modulator: real samples to a complex exponential whose instantaneous frequency is |
| [AM modulator](am_modulator.md) | `LiteDSPAMModulator` | 2 | 3 | AM modulator: ``envelope = 2**(dw-2) * (1 + m * x)`` with the modulation index ``m`` |
| [Gray mapper](gray_mapper.md) | `LiteDSPGrayMapper` | 1 | 0 | Binary to Gray (``g = b ^ (b >> 1)``) on ``n_lanes`` words of ``width`` bits per beat, so |
| [Gray demapper](gray_demapper.md) | `LiteDSPGrayDemapper` | 1 | 0 | Gray to binary (prefix XOR from the MSB) per lane. Latency 1. |
| [SSB modulator](ssb_modulator.md) | `LiteDSPSSBModulator` | 3 | 17 | SSB by the phasing method: ``s = x + j * sgn * hilbert(x)`` on a complex baseband |
| [FSK / GFSK modulator](fsk_modulator.md) | `LiteDSPFSKModulator` | 6 | 7 | M-ary FSK (2^bits_per_symbol levels) at ``sps`` samples per symbol, optionally Gaussian |
| [Line encoder (NRZI)](line_encoder.md) | `LiteDSPLineEncoder` | 1 | 0 | Bit stream to line code (``[("data", 1)]`` in and out). |
| [Line decoder (NRZI)](line_decoder.md) | `LiteDSPLineDecoder` | 1 | 0 | Line code to bits. NRZI: a bit from each level change (rate 1:1, latency 1). Manchester |
| [Manchester encoder](manchester_encoder.md) | `LiteDSPLineEncoder` | 1 | — | Bit stream to line code (``[("data", 1)]`` in and out). |
| [Manchester decoder](manchester_decoder.md) | `LiteDSPLineDecoder` | 1 | — | Line code to bits. NRZI: a bit from each level change (rate 1:1, latency 1). Manchester |
| [Hamming encoder](hamming_encoder.md) | `LiteDSPHammingEncoder` | var | 0 | Systematic Hamming encoder on a bit stream: ``k`` message bits in, the ``n = 2^m - 1`` |
| [Hamming decoder](hamming_decoder.md) | `LiteDSPHammingDecoder` | var | 0 | Hamming decoder: ``n (+1)`` codeword bits in, ``k`` corrected message bits out (framed). |
| [Convolutional interleaver](convolutional_interleaver.md) | `LiteDSPConvolutionalInterleaver` | 2 | 0 | Forney convolutional interleaver: branch ``j`` delays by ``j * depth`` symbols (DVB: |
| [Convolutional deinterleaver](convolutional_deinterleaver.md) | `LiteDSPConvolutionalDeinterleaver` | 2 | 0 | The matching deinterleaver: branch ``j`` delays by ``(B - 1 - j) * depth``; the pair |
| [HDLC framer](hdlc_framer.md) | `LiteDSPHDLCFramer` | var | 0 | Payload bits (LSB first, framed by ``last``) to an HDLC bit stream: ``preamble`` opening |
| [HDLC deframer](hdlc_deframer.md) | `LiteDSPHDLCDeframer` | var | 0 | HDLC bit stream to payload bits: flag detection, unstuffing, the X.25 FCS check. |
| [BCH encoder](bch_encoder.md) | `LiteDSPBCHEncoder` | var | 0 | Systematic BCH(n, k) encoder on a bit stream: ``k`` message bits pass through while an |
| [BCH decoder](bch_decoder.md) | `LiteDSPBCHDecoder` | var | 0 | Bit-serial BCH(n, k) decoder: ``n`` codeword bits in, ``k`` corrected message bits out. |
| [Phase modulator](pm_modulator.md) | `LiteDSPPhaseModulator` | 2 | 2 | PM modulator: the carrier phase (``phase_inc`` per sample) plus ``d / 2**(data_width-1) * |

## Analysis / Measurement (`analysis/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Window](window.md) | `LiteDSPWindow` | 2 | 2 | Apply a length-``n`` window to a complex I/Q stream, framed every ``n`` samples. |
| [FFT (SDF)](fft.md) | `LiteDSPFFT` | 63 | 28 | Streaming radix-2 SDF FFT, ``N`` points (power of two). |
| [FFT (iterative)](fft_iter.md) | `LiteDSPFFTIter` | 704 | 4 | Iterative in-place radix-2 FFT, ``N`` points, natural-order output (BRAM-mapped). |
| [FFT (parallel, P samples/clk)](parallel_fft.md) | `LiteDSPParallelFFT` | 76 | — | Streaming ``N``-point FFT at P samples/cycle (super-sample-rate wideband path). |
| [PSD](psd.md) | `LiteDSPPSD` | var | 2 | Power-spectral-density accumulator for a streaming FFT. |
| [Welch PSD](welch.md) | `LiteDSPWelchPSD` | var | — | Windowed, averaged power spectral density: Window -> FFT -> PSD, with segment overlap. |
| [Magnitude (approx)](magnitude.md) | `LiteDSPMagnitude` | 1 | 0 | Complex magnitude ``|I + jQ|``. |
| [Magnitude (CORDIC)](magnitude_cordic.md) | `LiteDSPMagnitude` | 19 | 1 | Complex magnitude ``|I + jQ|``. |
| [Goertzel](goertzel.md) | `LiteDSPGoertzel` | var | 17 | Single-bin DFT (tone detector) via a 2nd-order resonator — one multiplier. |
| [Stats](stats.md) | `LiteDSPStats` | 1 | 2 | Min / max / mean / variance of a real stream over ``2**window_log2`` samples. |
| [Histogram](histogram.md) | `LiteDSPHistogram` | var | 0 | Sample-distribution histogram (e.g. for ADC characterization). |
| [Energy detector](energy_detector.md) | `LiteDSPEnergyDetector` | 0 | — | Signal-presence detector with an adaptive noise floor (CFAR-style). |
| [Bit-reverse reorder](bit_reverse.md) | `LiteDSPBitReverse` | var | 0 | Reorder ``N``-beat frames from bit-reversed to natural order (the FFT's output order). |
| [Error counter](error_counter.md) | `LiteDSPErrorCounter` | var | 0 | Count mismatches between a reference and a received I/Q stream (synchronous join). |

## Stream Utilities (`stream/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Combine (sum)](combine.md) | `LiteDSPCombine` | 1 | 0 | Sum ``n_channels`` complex I/Q streams into one, with per-channel enable and saturation. |
| [Split (fan-out)](split.md) | `LiteDSPSplit` | 0 | — | Fan-out one stream to ``n`` identical sources (all consumed together). |
| [Delay](delay.md) | `LiteDSPDelay` | 1 | — | Delay a stream by ``depth`` cycles (payload and valid travel together). |
| [Skid buffer](skid_buffer.md) | `LiteDSPSkidBuffer` | 0 | — | Elastic timing-slack buffer for an I/Q stream (registers both valid and ready paths). |
| [Channel mux](channel_mux.md) | `LiteDSPChannelMux` | 0 | — | Route one of ``n`` sinks to a single source, selected by ``sel`` (runtime). |
| [Channel demux](channel_demux.md) | `LiteDSPChannelDemux` | 0 | — | Route a single sink to one of ``n`` sources, selected by ``sel`` (runtime). |
| [TDM mux (interleave)](tdm_mux.md) | `LiteDSPTDMMux` | 0 | 0 | Interleave ``n_channels`` mono streams into one channel-tagged TDM stream (strict |
| [TDM demux](tdm_demux.md) | `LiteDSPTDMDemux` | 0 | 0 | Split a channel-tagged TDM stream into ``n_channels`` mono streams: every beat is routed |
| [Capture (scope)](capture.md) | `LiteDSPCapture` | var | — | Scope-like capture: on a trigger, record ``depth`` I/Q samples to RAM, then stream them out. |
| [Conjugate](conjugate.md) | `LiteDSPConjugate` | 0 | — | Complex conjugate: ``q -> -q``. |
| [Swap I/Q](swap_iq.md) | `LiteDSPSwapIQ` | 0 | — | Swap I and Q (a +/-90 deg rotation / spectrum mirror). |
| [Negate](negate.md) | `LiteDSPNegate` | 0 | — | Negate both components. |
| [Stream FIFO](stream_fifo.md) | `LiteDSPStreamFIFO` | 0 | 0 | First-word-fall-through synchronous FIFO for an I/Q (or custom-``layout``) stream. |
| [I/Q pack](iq_pack.md) | `LiteDSPIQPack` | 0 | 0 | Pack ``ratio`` consecutive I/Q samples into one wide ``data`` word (LSB = first sample). |
| [I/Q unpack](iq_unpack.md) | `LiteDSPIQUnpack` | 0 | 0 | Unpack one wide ``data`` word into ``ratio`` I/Q samples (inverse of :class:`LiteDSPIQPack`). |
| [Clock-domain crossing](cdc.md) | `LiteDSPIQClockDomainCrossing` | 0 | — | Cross an I/Q stream between clock domains via a LiteX async FIFO. |
| [CSR source](csr_source.md) | `LiteDSPCSRSource` | var | 0 | Emit one I/Q sample per ``push`` strobe, with the payload set from CSR registers. |
| [CSR sink](csr_sink.md) | `LiteDSPCSRSink` | var | 0 | Always-ready sink that latches the last I/Q sample and counts transfers (CSR-readable). |
| [Null sink](null_sink.md) | `LiteDSPNullSink` | var | 0 | Always-ready drain that counts consumed samples (CSR-readable). Terminates a branch. |
| [Framer](framer.md) | `LiteDSPStreamFramer` | 0 | 0 | Pass I/Q through, asserting ``first`` at sample 0 and ``last`` at sample ``length-1``. |
| [Deframer](deframer.md) | `LiteDSPStreamDeframer` | 0 | — | Pass I/Q through, counting frames (on ``last``) and re-deriving ``first`` after each |
| [Timestamper](timestamper.md) | `LiteDSPTimestamper` | 0 | — | Tag the I/Q stream with its ingress time (``timestamp``/``stream_id`` params, latency 0). |
| [Time untagger](time_untagger.md) | `LiteDSPTimeUntagger` | 0 | — | Strip the ``timestamp``/``stream_id`` params: tagged I/Q -> plain I/Q (latency 0). |

## Motor Control (`motor/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Clarke (abc -> ab)](clarke.md) | `LiteDSPClarke` | 1 | 2 | Clarke transform: three-phase a/b/c -> stationary alpha/beta (amplitude-invariant). |
| [Inverse Clarke](inverse_clarke.md) | `LiteDSPInverseClarke` | 1 | 1 | Inverse Clarke transform: stationary alpha/beta -> three-phase a/b/c. |
| [Sin/Cos (angle)](sincos.md) | `LiteDSPSinCos` | 1 | 0 | Angle stream -> ``(cos, sin)`` unit vector on ``iq_layout`` (i = cos, q = sin). |
| [Angle ramp](angle_ramp.md) | `LiteDSPAngleRamp` | var | 0 | Free-running electrical-angle source: a phase accumulator emitting an angle stream. |
| [Park (ab -> dq)](park.md) | `LiteDSPPark` | 2 | 4 | Park transform: stationary alpha/beta + rotor angle -> rotating d/q. |
| [Inverse Park](inverse_park.md) | `LiteDSPInversePark` | 2 | 4 | Inverse Park transform: rotating d/q + rotor angle -> stationary alpha/beta. |
| [PI controller](pi_controller.md) | `LiteDSPPIController` | 1 | 2 | PI regulator on a real stream: ``u = clamp(kp*e + integral + feedforward, +/-limit)``. |
| [d/q current controller](dq_controller.md) | `LiteDSPDQController` | 1 | 4 | Two lock-stepped PI regulators on a d/q current vector -> d/q voltage command. |
| [Slew limiter](slew_limiter.md) | `LiteDSPSlewLimiter` | 1 | 0 | Rate limiter for references (speed/torque ramps): ``y += clamp(x - y, +/-rate)``. |
| [SVPWM modulator](svpwm.md) | `LiteDSPSVPWM` | 3 | 1 | Space-vector modulator: alpha/beta voltage vector -> three signed phase duties. |
| [3-phase PWM](pwm.md) | `LiteDSPPWM` | var | 1 | Center-aligned three-phase PWM with dead time, fault latch and ADC trigger (sink-only). |
| [Sigma-delta current sense](sigma_delta_filter.md) | `LiteDSPSigmaDeltaFilter` | 1 | 0 | Isolated sigma-delta current sense: per-phase sinc^N demodulators + fast trip path. |
| [Over-current trip](overcurrent_trip.md) | `LiteDSPOvercurrentTrip` | 0 | 0 | Window comparator on a three-phase stream: combinational passthrough + sticky trip. |
| [Quadrature encoder](quadrature_decoder.md) | `LiteDSPQuadratureDecoder` | var | 2 | Incremental encoder (A/B/Z) interface: position, direction, speed and electrical angle. |
| [Hall sensor decoder](hall_decoder.md) | `LiteDSPHallDecoder` | var | 0 | Three 120-degree Hall sensors -> sector, direction, speed and (interpolated) angle. |
| [Angle tracker (PLL)](angle_tracker.md) | `LiteDSPAngleTracker` | 1 | 0 | Type-II tracking loop on an angle stream: filtered angle + speed (angle PLL). |
| [Sliding-mode observer](smo_observer.md) | `LiteDSPSMObserver` | 19 | 4 | Sensorless sliding-mode back-EMF observer (PMSM, stationary alpha/beta frame). |
| [Resolver-to-digital](resolver.md) | `LiteDSPResolverDigital` | 21 | 5 | Resolver-to-digital converter: excitation output, synchronous demodulation, tracking loop. |
| [FOC current controller](foc.md) | `LiteDSPFOC` | 9 | 15 | Field-oriented current control: phase currents + rotor angle -> three-phase duties. |

## Audio Processing (`audio/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Volume (ramped)](volume.md) | `LiteDSPVolume` | 2 | 4 | Per-channel volume with zipper-free gain ramping and mute on a TDM audio stream. |
| [Stereo matrix (M/S, pan)](stereo_matrix.md) | `LiteDSPStereoMatrix` | 4 | 2 | 2x2 matrix on a stereo TDM stream: ``L' = a*L + b*R``, ``R' = c*L + d*R``. |
| [Dither / requantizer](dither.md) | `LiteDSPDither` | 1 | 0 | Word-length reduction with TPDF dither and optional error-feedback noise shaping. |
| [Parametric EQ](audio_eq.md) | `LiteDSPAudioEQ` | 25 | 4 | Multi-band, multi-channel parametric equalizer: a time-multiplexed biquad engine. |
| [Compressor](compressor.md) | `LiteDSPCompressor` | 15 | 5 | Dynamics processor (compressor, limiter, expander/gate) with a log-domain gain computer. |
| [Limiter (lookahead)](limiter.md) | `LiteDSPCompressor` | 15 | 5 | Dynamics processor (compressor, limiter, expander/gate) with a log-domain gain computer. |
| [Noise gate / expander](noise_gate.md) | `LiteDSPCompressor` | 15 | — | Dynamics processor (compressor, limiter, expander/gate) with a log-domain gain computer. |
| [LFO](lfo.md) | `LiteDSPLFO` | 1 | 1 | Low-frequency oscillator: sine (quarter-wave ROM), triangle, saw or square, with amplitude. |
| [Delay line (echo)](delay_line.md) | `LiteDSPDelayLine` | 7 | 2 | Feedback delay line with damping, wet/dry mix and optional modulated fractional delay. |
| [Chorus / flanger](chorus.md) | `LiteDSPDelayLine` | 9 | 2 | Feedback delay line with damping, wet/dry mix and optional modulated fractional delay. |
| [Wet/dry mix](wet_dry_mix.md) | `LiteDSPWetDryMix` | 1 | 4 | Two-input gain mix on TDM streams: ``y = dry*sink_dry + wet*sink_wet`` (signed Q1.15 gains). |
| [Reverb](reverb.md) | `LiteDSPReverb` | 1 | 16 | Schroeder / Freeverb-style reverb: parallel damped feedback combs, series allpasses, mix. |
| [Peak meter](peak_meter.md) | `LiteDSPPeakMeter` | 0 | 0 | Per-channel peak / hold / clip meter on a TDM stream (zero-latency passthrough tap). |
| [Loudness (BS.1770)](loudness.md) | `LiteDSPLoudness` | 0 | 8 | ITU-R BS.1770 loudness front-end: K-weighting + per-hop weighted sum of squares (zero-latency |
| [Sigma-delta modulator](sigma_delta_mod.md) | `LiteDSPSigmaDeltaModulator` | 1 | 0 | Error-feedback sigma-delta modulator: ``real_layout`` samples to a 1-bit stream at |
| [PDM DAC](sigma_delta_dac.md) | `LiteDSPSigmaDeltaDAC` | var | 0 | PDM DAC: a TDM (or mono) sink feeding one :class:`LiteDSPSigmaDeltaModulator` per channel, |
| [PDM receiver](pdm_rx.md) | `LiteDSPPDMReceiver` | var | 0 | PDM microphone receiver: :class:`LiteDSPBitstreamInterface` (``mclk`` out at ``sys_clk / |
| [I2S receiver](i2s_rx.md) | `LiteDSPI2SReceiver` | var | 0 | Serial audio receiver (I2S, left/right-justified, TDM) to a channel-tagged TDM stream. |
| [I2S transmitter](i2s_tx.md) | `LiteDSPI2STransmitter` | var | 0 | Channel-tagged TDM stream to serial audio (I2S, left/right-justified, TDM); the mirror of |

## Image / Video Processing (`image/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Pixel pattern source](pixel_pattern.md) | `LiteDSPPixelPattern` | var | 0 | Framed raster test-pattern source (``pixel_layout``), geometry from CSRs. |
| [Pixels from LiteX video](pixel_from_video.md) | `LiteDSPPixelFromVideo` | 1 | 0 | LiteX ``video_data_layout`` stream to a framed RGB pixel stream. |
| [Pixels to LiteX video](pixel_to_video.md) | `LiteDSPPixelToVideo` | 1 | 0 | Framed RGB pixels onto a LiteX timing-generator stream (``video_timing_layout``) as a |
| [Line buffer (window)](line_buffer.md) | `LiteDSPLineBuffer` | 69 | 0 | Sliding ``kernel_size x kernel_size`` window over a raster pixel stream. |
| [2-D kernel (3x3)](kernel_2d.md) | `LiteDSPKernel2D` | 71 | 9 | ``kernel_size x kernel_size`` correlation kernel on a raster stream (per channel). |
| [2-D kernel (5x5)](kernel_5x5.md) | `LiteDSPKernel2D` | 139 | 25 | ``kernel_size x kernel_size`` correlation kernel on a raster stream (per channel). |
| [Gaussian blur](gaussian_blur.md) | `LiteDSPKernel2D` | 71 | — | ``kernel_size x kernel_size`` correlation kernel on a raster stream (per channel). |
| [Sharpen](sharpen.md) | `LiteDSPKernel2D` | 71 | — | ``kernel_size x kernel_size`` correlation kernel on a raster stream (per channel). |
| [Laplacian](laplacian.md) | `LiteDSPKernel2D` | 71 | — | ``kernel_size x kernel_size`` correlation kernel on a raster stream (per channel). |
| [Sobel edge magnitude](sobel.md) | `LiteDSPSobel` | 72 | 1 | Sobel edge magnitude on a mono raster stream. |
| [Rank filter (median)](rank_filter.md) | `LiteDSPRankFilter` | 73 | 0 | Rank-order filter on a 3x3 neighbourhood (per channel). |
| [Erosion (3x3 min)](erode.md) | `LiteDSPRankFilter` | 73 | — | Rank-order filter on a 3x3 neighbourhood (per channel). |
| [Dilation (3x3 max)](dilate.md) | `LiteDSPRankFilter` | 73 | — | Rank-order filter on a 3x3 neighbourhood (per channel). |
| [Threshold (hysteresis)](threshold.md) | `LiteDSPThreshold` | 1 | 0 | Binary threshold with hysteresis along the scan line (mono). |
| [Pixel gain / offset](pixel_gain.md) | `LiteDSPPixelGain` | 2 | 3 | Per-channel gain and offset: ``y = clamped(rounded(x * gain, gain_frac) + offset)``. |
| [Pixel LUT](pixel_lut.md) | `LiteDSPPixelLUT` | 1 | 0 | Code-to-code lookup on every channel (``2**data_width`` entries per table). |
| [Gamma (LUT)](gamma.md) | `LiteDSPPixelLUT` | 1 | — | Code-to-code lookup on every channel (``2**data_width`` entries per table). |
| [Colour matrix](color_matrix.md) | `LiteDSPColorMatrix` | 3 | 9 | ``y_c = clamped(rounded(sum_k m[c][k] * (x_k - in_off_k), coeff_frac) + out_off_c)`` on RGB |
| [RGB to YCbCr (601)](rgb_to_ycbcr.md) | `LiteDSPColorMatrix` | 3 | — | ``y_c = clamped(rounded(sum_k m[c][k] * (x_k - in_off_k), coeff_frac) + out_off_c)`` on RGB |
| [YCbCr to RGB (601)](ycbcr_to_rgb.md) | `LiteDSPColorMatrix` | 3 | — | ``y_c = clamped(rounded(sum_k m[c][k] * (x_k - in_off_k), coeff_frac) + out_off_c)`` on RGB |
| [RGB to grey (601)](rgb_to_gray.md) | `LiteDSPColorMatrix` | 3 | — | ``y_c = clamped(rounded(sum_k m[c][k] * (x_k - in_off_k), coeff_frac) + out_off_c)`` on RGB |
| [Debayer (bilinear)](debayer.md) | `LiteDSPDebayer` | 71 | 0 | Bilinear demosaic of a raw Bayer (mono) stream into RGB. |
| [Box downscaler](downscaler.md) | `LiteDSPDownscaler` | 2 | 0 | Exact box-mean downscaling by ``decimation`` (2, 4 or 8) in both directions. |
| [Crop (ROI)](crop.md) | `LiteDSPCrop` | 1 | 0 | Pass a rectangular region of interest, consume everything else. |
| [Frame statistics tap](pixel_stats.md) | `LiteDSPPixelStats` | 0 | 0 | Zero-latency passthrough that measures one channel per frame. |
| [Frame histogram](pixel_histogram.md) | `LiteDSPPixelHistogram` | var | 0 | Histogram of one channel per frame into ``2**bins_log2`` bins (the code's top bits). |
| [Alpha blend](alpha_blend.md) | `LiteDSPAlphaBlend` | 1 | 6 | ``y = rounded(a * A + (256 - a) * B, 8)`` per channel over two lock-stepped pixel streams. |
| [Mask blend](mask_blend.md) | `LiteDSPAlphaBlend` | 1 | — | ``y = rounded(a * A + (256 - a) * B, 8)`` per channel over two lock-stepped pixel streams. |
| [Box overlay](box_overlay.md) | `LiteDSPBoxOverlay` | 1 | 0 | Draw up to ``n_boxes`` rectangle outlines on a pixel stream. |
| [Pixel FIFO](pixel_fifo.md) | `LiteDSPPixelFIFO` | 0 | 0 | Elastic buffer for a pixel stream (``pixel_layout``, tags carried). |
| [Pixel pack](pixel_pack.md) | `LiteDSPPixelPack` | 0 | 0 | Pack pixels into memory words: ``rgb888`` (``r`` in the low byte, then ``g``, ``b``), |
| [Pixel unpack](pixel_unpack.md) | `LiteDSPPixelUnpack` | 1 | 0 | Unpack memory words back into pixels (inverse of :class:`LiteDSPPixelPack`; ``rgb565`` |

## Radar / Sonar Processing (`radar/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Pulse generator](pulse_generator.md) | `LiteDSPPulseGenerator` | var | 0 | Transmit pulse train: a linear-FM chirp of ``pulse_len`` samples every ``pri`` samples. |
| [Range gate (PRI timer)](range_gate.md) | `LiteDSPRangeGate` | 1 | 0 | PRI / CPI timer and receive gate: turns a continuous I/Q stream into framed pulses. |
| [MTI canceller](mti.md) | `LiteDSPMTICanceller` | 2 | 0 | Two- or three-pulse MTI canceller on framed pulses (one frame = ``n_range_bins`` beats). |
| [Corner turn (fast to slow time)](corner_turn.md) | `LiteDSPCornerTurn` | var | 0 | Transpose a CPI of ``n_pulses`` framed pulses (``n_range_bins`` beats each) into |
| [CA-CFAR detector](ca_cfar.md) | `LiteDSPCACFAR` | var | 2 | One-dimensional cell-averaging CFAR detector on framed cell streams. |
| [OS-CFAR detector](os_cfar.md) | `LiteDSPOSCFAR` | var | 1 | One-dimensional ordered-statistic CFAR detector on framed cell streams. |
| [Clutter map](clutter_map.md) | `LiteDSPClutterMap` | 4 | 2 | Scan-to-scan clutter map detector on framed cell streams. |
| [2-D CA-CFAR detector](cfar_2d.md) | `LiteDSPCFAR2D` | var | 5 | Cell-averaging CFAR over a ``(2R+1) x (2C+1)`` box of a range-Doppler map. |
| [Peak extractor](peak_extractor.md) | `LiteDSPPeakExtractor` | var | 0 | Detected cells to sparse target records with sub-bin centroids. |
| [Target list](target_list.md) | `LiteDSPTargetList` | var | 0 | Per-CPI target list buffer with host readback. |
| [Kalman tracker](kalman_tracker.md) | `LiteDSPKalmanTracker` | var | 20 | Constant-velocity Kalman tracker over ``n_tracks`` slots (same stream contract, association, |
| [Beamformer](beamformer.md) | `LiteDSPBeamformer` | 3 | 16 | Narrowband phase-shift beamformer: ``n_elements`` I/Q streams to ``n_beams`` beams. |
| [Monopulse angle](monopulse.md) | `LiteDSPMonopulse` | 21 | 4 | Phase-comparison monopulse: the phase of ``a * conj(b)`` for two element / sub-array |
| [Time-varying gain](tvg.md) | `LiteDSPTVG` | 6 | 6 | Time-varying gain: a log-domain gain ramp along the range bins of each frame. |
| [Alpha-beta tracker](alpha_beta_tracker.md) | `LiteDSPAlphaBetaTracker` | var | 8 | Alpha-beta tracker over ``n_tracks`` slots fed by per-CPI target bursts. |
| [Doppler processor](doppler.md) | `LiteDSPDopplerProcessor` | var | 14 | Slow-time columns (``n_pulses`` beats per range bin) to range-Doppler map rows. |
| [Pulse compressor (chirp matched filter)](pulse_compressor.md) | `LiteDSPPulseCompressor` | 4 | 60 | Matched filter for the linear-FM pulse of :class:`~litedsp.generation.source.LiteDSPChirp` |
