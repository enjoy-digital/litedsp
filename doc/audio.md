# Audio processing blocks

The `litedsp/audio/` family covers the signal path of a digital audio product on the same stream
contract as the RF and motor blocks (`doc/interfaces.md`): converters (I2S, PDM microphones,
sigma-delta DACs), tone and dynamics processing (parametric EQ, compressor/limiter/gate, volume,
stereo matrix), effects (delay/chorus, reverb, LFO), metering (peak/clip, BS.1770 loudness) and
word-length reduction (TPDF dither with noise shaping). Every block is a `LiteDSP`-prefixed
`LiteXModule` with `valid`/`ready` streams, control signals mapped to CSRs, a bit-exact NumPy
golden model and, where the generic testbench applies, Verilator co-simulation. The per-block
datasheets are in `doc/blocks/`; [AN010](app_notes/an010_audio_processor.md) runs a complete
I2S-to-I2S chain.

## Conventions

| Item | Convention |
|---|---|
| Sample format | Signed Q1.23 in a 24-bit `data` field by default (`data_width=24`); every block is width-parameterized |
| Multi-channel audio | One **channel-tagged TDM stream**: `tdm_layout(data_width, n_channels)` = `real_layout` + an unsigned `channel` tag (L = 0, R = 1, ...). Beats of a frame are consecutive, channel 0 first; `n_channels=1` degenerates to a plain `real_layout` mono stream |
| Gains | Volume: unsigned Q5.(N-5) (up to +30 dB); mix/matrix coefficients: signed Q1.15 or Q3.15; dynamics: log2 domain, Q.8 (256 = 6.02 dB) |
| Filter coefficients | EQ sections Q4.28 (`biquad_sos_quantize(rows, 32, 28)`) designed with `litedsp.audio.design.rbj_biquad` (RBJ cookbook) and friends |
| Time constants | One-pole smoother coefficients Q0.16 from `time_constant_coeff(ms, sample_rate)` |
| Bypass | Layout-preserving in-line blocks carry a `bypass` control (exact passthrough, tag included) |

## Two engine styles

*Pipelined blocks* (volume, dither, meters, wet/dry mix, TDM mux/demux, bitstream decimator)
accept one beat per clock. *Serial engines* (EQ, compressor, stereo matrix, delay line, reverb)
time-multiplex a single multiplier over a few cycles per beat and expose the budget as
`cycles_per_sample`; an audio stream is slow compared to the fabric clock, so the budget only
bounds the minimum system clock:

| Block | Cycles per beat | Minimum `sys_clk` for 48 kHz stereo |
|---|---|---|
| `LiteDSPAudioEQ` (3 bands) | 26 | 2.5 MHz |
| `LiteDSPCompressor` | 16 | 1.6 MHz |
| `LiteDSPStereoMatrix` | 8 per frame | 0.4 MHz |
| `LiteDSPDelayLine` | 10 (12 modulated) | 1.2 MHz |
| `LiteDSPReverb` (4 combs + 2 allpasses, parallel) | 10 | 1.0 MHz |

Serial engines apply back-pressure while busy; a converter tap that must never stall the line
(`LiteDSPLoudness`) drops the beat and sets a sticky `overrun` flag instead.

## Converters and clocking

* **I2S / left-justified / right-justified / TDM** (`LiteDSPI2SReceiver`, `LiteDSPI2STransmitter`):
  everything runs in the `sys` domain. A *master* divides `sys_clk` into BCLK (`bclk_div`, even,
  >= 4) and drives LRCK/SDATA on the falling edge; a *slave* synchronizes BCLK/LRCK/SDATA with
  two flip-flops and detects edges, so `sys_clk` must be at least 4 x BCLK to receive and 8 x
  BCLK to transmit. Slots are 16/24/32 bits with `sample_width <= min(slot_width, data_width)`
  samples MSB-aligned into `data_width`; TDM frames carry 2/4/8 slots after a one-BCLK sync
  pulse.
* **PDM microphones** (`LiteDSPPDMReceiver`): `mclk = sys/clk_div`, the 1-bit line(s) sampled
  after the falling (and, dual-edge, rising) edge feed one `LiteDSPBitstreamDecimator` (sinc^N,
  runtime rate) per channel, a mono `LiteDSPDCBlocker` and an optional CIC droop-compensation
  FIR; the output is a TDM stream at `sys / (clk_div * decimation)` frames per second.
* **Sigma-delta DAC** (`LiteDSPSigmaDeltaModulator`, `LiteDSPSigmaDeltaDAC`): second-order
  error-feedback modulator with zero-order hold (`interpolation` bits per sample, keep the input
  below about -3 dBFS), clocked out on `pdm_out`/`pdm_clk` at `sys/clk_div`.

## Host-side math

`litedsp.audio.design` holds the NumPy design helpers (RBJ biquads, Linkwitz-Riley crossovers,
BS.1770 K-weighting, dB <-> linear / log2 conversions, time constants, pan and mid/side
matrices) and `litedsp.software.drivers` the typed drivers that speak Hz/dB/ms:
`AudioEQDriver.set_bands([...])` designs, quantizes, loads the shadow set and commits;
`CompressorDriver.set_threshold_db/set_ratio/set_attack_ms`; `VolumeDriver.set_db`;
`StereoMatrixDriver.pan/width/ms_encode`; `LFODriver.set_frequency`; `PeakMeterDriver.read_dbfs`;
`LoudnessDriver.momentary/short_term/integrated` (gated per BS.1770-4 from the block's hop sums).

## Quality figures (from the tests and characterization)

* Dither: a -60 dBFS tone truncated 24 -> 16 bits regains >= 20 dB SFDR with TPDF dither; the
  second-order error-feedback shaper lowers the 0..0.1 fs noise by more than 6 dB.
* EQ: DF1 with first-order error feedback keeps the 40 Hz peaking band's residual noise more than
  10 dB below the plain DF1 (theory ~25 dB); the response matches the float design within 0.2 dB.
* Compressor: static curve within 0.15 dB of the design (LUT log2/exp2); the limiter holds a
  0 dBFS sine at its ceiling within 0.5 dB with 32 frames of lookahead.
* PDM receiver: a -6 dBFS tone through the second-order modulator model and the OSR-64 sinc^4
  decimator reads >= 45 dB SNR per channel; droop compensation flattens 0.15 fs to within 0.5 dB.
* Loudness: a -20 dBFS 997 Hz stereo tone reads within 0.2 dB of the K-weighted design.
