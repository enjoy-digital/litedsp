# LiteDSP Block Catalog

114 blocks, generated from the block registry by `litedsp/flow/docgen.py` (do not edit by hand — regenerate with `python3 -m litedsp.flow.docgen`).

## Signal Generation (`generation/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [NCO (DDS)](nco.md) | `LiteDSPNCO` | 1 | 0 | Numerically-Controlled Oscillator (a.k.a. DDS). |
| [CORDIC (rotate)](cordic_rot.md) | `LiteDSPCORDIC` | 18 | 2 | Pipelined CORDIC (one iteration per stage), gain-compensated, full-circle. |
| [CORDIC (vector)](cordic_vec.md) | `LiteDSPCORDIC` | 18 | 1 | Pipelined CORDIC (one iteration per stage), gain-compensated, full-circle. |
| [Chirp (LFM)](chirp.md) | `LiteDSPChirp` | var | — | Linear-FM (chirp) I/Q generator: the instantaneous frequency ramps by ``rate`` per sample. |
| [Noise (AWGN)](noise_source.md) | `LiteDSPNoiseSource` | var | — | Approximate-Gaussian (AWGN) complex noise via summed xorshift32 streams (CLT). |
| [Pattern source](pattern_source.md) | `LiteDSPPatternSource` | var | 0 | I/Q test-pattern generator (constant / counter ramp / PRBS / impulse). |

## Mixing / Frequency Translation (`mixing/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Mixer (complex)](mixer.md) | `LiteDSPMixer` | 2 | 4 | Complex mixer with runtime up/down mode and bypass. |
| [DDC](ddc.md) | `LiteDSPDDC` | 1 | 6 | Digital down-converter: NCO + complex mixer (down) + decimator. |
| [DUC](duc.md) | `LiteDSPDUC` | 1 | 7 | Digital up-converter: interpolator + complex mixer (up) + NCO. |
| [Channelizer](channelizer.md) | `LiteDSPChannelizer` | 34 | 24 | Split a wide band into ``n_channels`` uniformly-spaced sub-channels. |
| [PFB channelizer](pfb_channelizer.md) | `LiteDSPPFBChannelizer` | 60 | 11 | Critically-sampled uniform DFT filter bank (polyphase FIR + direct M-point DFT). |

## Filtering (`filter/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [FIR (real)](fir_real.md) | `LiteDSPFIRFilter` | 3 | — | Pipelined single-rate real FIR filter with stream I/O and round+saturate output. |
| [FIR (complex)](fir_complex.md) | `LiteDSPFIRFilterComplex` | 3 | 2 | Complex FIR: identical real FIRs on I and Q, shared coefficients, with bypass + CSR. |
| [FIR decimator](fir_decimator.md) | `LiteDSPFIRDecimator` | 33 | 2 | Decimate-by-R complex FIR with a single time-shared MAC per I/Q. |
| [FIR interpolator](fir_interpolator.md) | `LiteDSPFIRInterpolator` | 32 | 2 | Interpolate-by-L complex FIR with a single time-shared MAC per I/Q (polyphase). |
| [CIC decimator](cic_decimator.md) | `LiteDSPCICDecimator` | 1 | 0 | CIC decimator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N``, rescaled to width. |
| [CIC interpolator](cic_interpolator.md) | `LiteDSPCICInterpolator` | 1 | 0 | CIC interpolator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N / R``, rescaled. |
| [Halfband decimator](halfband_dec.md) | `LiteDSPHalfbandDecimator` | 24 | — | Decimate-by-2 half-band FIR. |
| [Halfband interpolator](halfband_int.md) | `LiteDSPHalfbandInterpolator` | 23 | — | Interpolate-by-2 half-band FIR. |
| [Hilbert](hilbert.md) | `LiteDSPHilbert` | 3 | — | Real -> analytic (complex) signal via a Hilbert FIR. |
| [IIR biquad](iir_biquad.md) | `LiteDSPIIRBiquad` | 2 | 24 | One DF2T biquad section applied to I and Q with shared coefficients. |
| [DC blocker](dc_blocker.md) | `LiteDSPDCBlocker` | 1 | 0 | Multiplier-free 1st-order DC-removal IIR (per I/Q). |
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

## Impairment Correction (`correction/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [DC offset](dc_offset.md) | `LiteDSPDCOffset` | 1 | — | Estimate and remove a DC offset per I/Q with a leaky-integrator mean. |
| [I/Q balance](iq_balance.md) | `LiteDSPIQBalance` | 1 | — | Correct I/Q gain & phase imbalance with a 2x2 matrix, plus an estimator for calibration. |
| [Derotator (CFO)](derotator.md) | `LiteDSPDerotator` | 2 | — | Frequency-shift (derotate) an I/Q stream by ``-phase_inc`` (NCO + down-mixer). |

## Communications (`comm/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [FM demod](fm_demod.md) | `LiteDSPFMDemod` | 18 | 4 | FM discriminator: instantaneous frequency = ``angle(x[n] * conj(x[n-1]))``. |
| [AM demod](am_demod.md) | `LiteDSPAMDemod` | 2 | — | AM envelope demodulator: ``|x|`` (magnitude) with the carrier DC removed. |
| [Slicer](slicer.md) | `LiteDSPSlicer` | 1 | — | Hard-decision QAM slicer: map each of I/Q to the nearest PAM level. |
| [Soft demapper (LLR)](soft_demapper.md) | `LiteDSPSoftDemapper` | 2 | 2 | Gray-coded square-QAM max-log soft demapper: per-axis folded piecewise-linear LLRs. |
| [Symbol mapper](symbol_mapper.md) | `LiteDSPSymbolMapper` | 1 | — | Map a QAM symbol index to a constellation I/Q point (inverse of :class:`LiteDSPSlicer`). |
| [Correlator](correlator.md) | `LiteDSPCorrelator` | 3 | 14 | Sliding correlation of the I/Q stream against a known real ``sequence``. |
| [Frame sync (preamble)](frame_sync.md) | `LiteDSPFrameSync` | 9 | 23 | Preamble detector + stream aligner: the gateway block for burst receivers. |
| [Timing recovery (M&M)](timing_recovery.md) | `LiteDSPTimingRecovery` | var | 16 | Symbol timing recovery with an interpolation controller (M&M or Gardner detector). |
| [Carrier loop (PLL)](carrier_loop.md) | `LiteDSPCarrierLoop` | 1 | — | Carrier recovery: derotate the input with an internal NCO driven by a PI loop. |
| [Phase detector](phase_detect.md) | `LiteDSPPhaseDetect` | 18 | — | Instantaneous phase ``atan2(Q, I)`` of an I/Q stream (CORDIC vectoring). |
| [CFO estimator (coarse)](cfo_estimator.md) | `LiteDSPCFOEstimator` | 0 | 4 | Coarse CFO estimator: delay-conjugate-multiply autocorrelation + CORDIC angle. |
| [Differential encoder](diff_encoder.md) | `LiteDSPDifferentialEncoder` | 1 | — | ``out[n] = (in[n] + out[n-1]) mod M`` (symbol indices). |
| [Differential decoder](diff_decoder.md) | `LiteDSPDifferentialDecoder` | 1 | — | ``out[n] = (in[n] - in[n-1]) mod M`` (inverse of the encoder). |
| [Scrambler (LFSR)](scrambler.md) | `LiteDSPScrambler` | 1 | — | Self-synchronizing multiplicative scrambler ``y = x ^ y[-t1] ^ y[-t2] ...`` (bit-serial). |
| [Descrambler (LFSR)](descrambler.md) | `LiteDSPDescrambler` | 1 | — | Inverse of :class:`LiteDSPScrambler` ``x = y ^ y[-t1] ^ y[-t2] ...`` (self-synchronizing). |
| [CRC](crc.md) | `LiteDSPCRC` | 1 | — | Bit-serial MSB-first CRC; passes ``data`` through and updates the ``crc`` register. |
| [Convolutional encoder](conv_encoder.md) | `LiteDSPConvEncoder` | 1 | — | Rate-1/2 convolutional encoder (default K=7, G=[0o171, 0o133]). |
| [Viterbi decoder](viterbi_decoder.md) | `LiteDSPViterbiDecoder` | 1 | 0 | Hard/soft-decision Viterbi decoder (rate 1/n, register-exchange survivors). |
| [Puncturer](puncturer.md) | `LiteDSPPuncturer` | var | 0 | TX puncturer: drops coded bits of the rate-1/n stream per the puncturing matrix. |
| [Depuncturer (LLR)](depuncturer.md) | `LiteDSPDepuncturer` | var | 0 | RX depuncturer: reassembles full soft symbols, reinserting erasures (LLR 0) per pattern. |
| [Block interleaver](block_interleaver.md) | `LiteDSPBlockInterleaver` | var | 0 | TX block interleaver: rows x cols symbols in row-wise, out column-wise. |
| [Block deinterleaver](block_deinterleaver.md) | `LiteDSPBlockDeinterleaver` | var | 0 | RX block deinterleaver: the exact inverse of :class:`LiteDSPBlockInterleaver`. |
| [RS encoder (255,k)](rs_encoder.md) | `LiteDSPRSEncoder` | var | 0 | Systematic RS(255, k) encoder: k message bytes in, n = 255 codeword bytes out. |
| [RS decoder (255,k)](rs_decoder.md) | `LiteDSPRSDecoder` | var | 0 | RS(255, k) decoder: n = 255 codeword bytes in, k corrected message bytes out. |
| [LDPC encoder (802.11n)](ldpc_encoder.md) | `LiteDSPLDPCEncoder` | var | 0 | 802.11n rate-1/2 (648, 324) LDPC encoder: 324 message bits in, 648 codeword bits out. |
| [LDPC decoder (802.11n)](ldpc_decoder.md) | `LiteDSPLDPCDecoder` | var | 0 | 802.11n rate-1/2 (648, 324) LDPC decoder: 648 LLRs in, 324 corrected bits out. |
| [OFDM CP insert](cp_insert.md) | `LiteDSPCPInsert` | var | — | Insert a cyclic prefix: N-sample symbols in, (CP + N)-sample symbols out. |
| [OFDM CP remove](cp_remove.md) | `LiteDSPCPRemove` | 0 | — | Remove a cyclic prefix: (CP + N)-sample symbols in, framed N-sample symbols out. |
| [OFDM equalizer (1-tap)](ofdm_equalizer.md) | `LiteDSPOFDMEqualizer` | 2 | 6 | LS channel estimation + divider-free one-tap OFDM equalizer with per-bin CSI. |

## Analysis / Measurement (`analysis/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Window](window.md) | `LiteDSPWindow` | 2 | 2 | Apply a length-``n`` window to a complex I/Q stream, framed every ``n`` samples. |
| [FFT (SDF)](fft.md) | `LiteDSPFFT` | 63 | 28 | Streaming radix-2 SDF FFT, ``N`` points (power of two), 1 sample/cycle. |
| [FFT (iterative)](fft_iter.md) | `LiteDSPFFTIter` | 704 | 4 | Iterative in-place radix-2 FFT, ``N`` points, natural-order output (BRAM-mapped). |
| [FFT (parallel, 2 samples/clk)](parallel_fft.md) | `LiteDSPParallelFFT` | 76 | — | Streaming ``N``-point FFT at 2 samples/cycle (super-sample-rate wideband path). |
| [PSD](psd.md) | `LiteDSPPSD` | var | 2 | Power-spectral-density accumulator for a streaming FFT. |
| [Welch PSD](welch.md) | `LiteDSPWelchPSD` | var | — | Windowed, averaged power spectral density: Window -> FFT -> PSD, with segment overlap. |
| [Magnitude (approx)](magnitude.md) | `LiteDSPMagnitude` | 1 | 0 | Complex magnitude ``|I + jQ|``. |
| [Magnitude (CORDIC)](magnitude_cordic.md) | `LiteDSPMagnitude` | 18 | 1 | Complex magnitude ``|I + jQ|``. |
| [Goertzel](goertzel.md) | `LiteDSPGoertzel` | var | 17 | Single-bin DFT (tone detector) via a 2nd-order resonator — one multiplier. |
| [Stats](stats.md) | `LiteDSPStats` | 1 | 2 | Min / max / mean / variance of a real stream over ``2**window_log2`` samples. |
| [Histogram](histogram.md) | `LiteDSPHistogram` | var | 0 | Sample-distribution histogram (e.g. for ADC characterization). |
| [Energy detector](energy_detector.md) | `LiteDSPEnergyDetector` | 0 | — | Signal-presence detector with an adaptive noise floor (CFAR-style). |
| [Error counter](error_counter.md) | `LiteDSPErrorCounter` | var | 0 | Count mismatches between a reference and a received I/Q stream (synchronous join). |

## Stream Utilities (`stream/`)

| Block | Class | Latency | DSP | Description |
|---|---|---|---|---|
| [Combine (sum)](combine.md) | `LiteDSPCombine` | 1 | 0 | Sum ``n_channels`` complex I/Q streams into one, with per-channel enable and saturation. |
| [Split (fan-out)](split.md) | `LiteDSPSplit` | 0 | — | Fan-out one I/Q stream to ``n`` identical sources (all consumed together). |
| [Delay](delay.md) | `LiteDSPDelay` | 1 | — | Delay an I/Q stream by ``depth`` cycles (data and valid travel together). |
| [Skid buffer](skid_buffer.md) | `LiteDSPSkidBuffer` | 0 | — | Elastic timing-slack buffer for an I/Q stream (registers both valid and ready paths). |
| [Channel mux](channel_mux.md) | `LiteDSPChannelMux` | 0 | — | Route one of ``n`` I/Q sinks to a single source, selected by ``sel`` (runtime). |
| [Channel demux](channel_demux.md) | `LiteDSPChannelDemux` | 0 | — | Route a single I/Q sink to one of ``n`` sources, selected by ``sel`` (runtime). |
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
| [Deframer](deframer.md) | `LiteDSPStreamDeframer` | 0 | — | Pass I/Q through, counting frames (on ``last``) and re-deriving ``first`` after each frame. |
| [Timestamper](timestamper.md) | `LiteDSPTimestamper` | 0 | — | Tag the I/Q stream with its ingress time (``timestamp``/``stream_id`` params, latency 0). |
| [Time untagger](time_untagger.md) | `LiteDSPTimeUntagger` | 0 | — | Strip the ``timestamp``/``stream_id`` params: tagged I/Q -> plain I/Q (latency 0). |
