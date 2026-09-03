# LiteDSP Examples

Each script assembles real LiteDSP blocks into a chain and runs it (NumPy stimulus + the
`test/common.py` stream simulator), printing a result and asserting a golden property. Run any
with `python3 examples/<name>.py`.

| Example | Chain | Demonstrates |
|---|---|---|
| `ddc_chain.py` | NCO → Mixer(down) → FIR → Downsampler | Digital down-conversion, tone rejection |
| `duc_chain.py` | Interpolator → NCO → Mixer(up) | Digital up-conversion |
| `fm_receiver.py` | FMDemod → FIR decimator | FM discriminator + audio decimation |
| `qpsk_rx.py` | RRC matched filter → TimingRecovery → Slicer | Symbol timing recovery, QPSK demod (SER 0) |
| `spectrum_analyzer.py` | Window → FFT → PSD | Averaged power spectrum |
| `wideband_rx.py` | DDC → StreamFIFO → StreamFramer → IQPack | Capture front-end: elastic buffering, framing (→ AXI-Stream `tlast`), packing narrow I/Q into wide bus words |
| `loopback_ber.py` | PatternSource(PRBS) → Split → {Delay \| StreamFIFO} → ErrorCounter | Self-checking BER/integrity harness from the bring-up blocks |
| `integrated_ip.py` | DCBlocker → Gain → Framer, AXI-Stream ports | Preview of the integratable IP target: AXI-Stream data ports + aggregated CSR register map (`get_csrs()`) + generated Verilog |

`wideband_rx`, `loopback_ber`, and `integrated_ip` exercise the chain-glue / bus-I/O / measurement
blocks (FIFO, pack, pattern source, error counter, framer) and preview the flow-graph → AXI IP-core
direction (see `litedsp/flow/` and `doc/flow.md`).

## Application notes

Flagship examples paired with a documented app note (objective, block diagram, resource totals,
measured results and committed plots) under [`doc/app_notes/`](../doc/app_notes/). All run
headless (matplotlib Agg, `savefig` only) and are smoke-checked in CI (`test/test_examples.py`).

| App note | Example | Chain | Demonstrates / golden property |
|---|---|---|---|
| [AN001 — FM stereo broadcast receiver](../doc/app_notes/an001_fm_stereo.md) | `fm_stereo_receiver.py` | FMDemod → pilot BP → Mixer(square) → 38 kHz BP → Mixer → FIR decimators → IQAdd matrix | Pilot-squaring stereo decode: separation ≥ 30 dB, audio SNR ≥ 25 dB (L-only program) |
| [AN002 — DQPSK modem loopback + BER curve](../doc/app_notes/an002_qpsk_modem.md) | `qpsk_modem.py` | PRBS → DiffEncoder → SymbolMapper → PulseShaper → AWGN → matched RRC → TimingRecovery → Slicer → DiffDecoder | BER vs Eb/N0 vs DQPSK theory: implementation loss < 1 dB @ 1e-3; one RTL point == golden models |
| [AN003 — Spectrum monitor with waterfall](../doc/app_notes/an003_spectrum_monitor.md) | `spectrum_monitor.py` | TimeCore/Timestamper → TimeUntagger → WelchPSD (50% overlap, linear + max-hold) | Timestamped waterfall (absolute sample time), averaged vs max-hold spectra, GNU Radio `udp_source` interop recipe |
| [AN004 — Chirp pulse-compression radar](../doc/app_notes/an004_chirp_radar.md) | `chirp_radar.py` | Chirp → NumPy target channel → complex matched filter (2 × FIRFilterComplex) → Magnitude | Pulse-compression ranging (exact delay recovery), range resolution vs bandwidth, PSLR gate |
| [AN005 — CCSDS concatenated-FEC telemetry](../doc/app_notes/an005_ccsds_telemetry.md) | `ccsds_telemetry.py` | dual-basis CCSDS RSEncoder ×I → BlockInterleaver → ConvEncoder(K=7) → QPSK/AWGN + jammer burst → SoftDemapper → soft Viterbi → BlockDeinterleaver → CCSDS RSDecoder | Burst spreading: a burst that is uncorrectable without interleaving is fully corrected at I = 2 (~I× correctable burst); RTL end-to-end recovers the message error-free |
| [AN006 — ADS-B / Mode-S receiver](../doc/app_notes/an006_adsb_receiver.md) | `adsb_receiver.py` | 2 MHz magnitude → Correlator → PPM → DF17/CRC-24 | Exact acquisition, parsed ICAO/type code, zero syndrome, and corruption rejection |
| [AN007 — AIS GMSK receiver](../doc/app_notes/an007_ais_receiver.md) | `ais_receiver.py` | GMSK → FMDemod → NRZI → HDLC flags/unstuff/FCS | Exact training/flag acquisition, zero payload errors, and corruption rejection |
| [AN008 — Chirp spread-spectrum receiver](../doc/app_notes/an008_css_receiver.md) | `css_receiver.py` | Preamble acquire → RTL CFO estimate → dechirp/FFT | Exact start, ≤0.05-bin CFO error, and SF7 payload recovery |
| [AN010 — Stereo audio processor](../doc/app_notes/an010_audio_processor.md) | `audio_processor.py` | AudioEQ → Volume → PeakMeter → Dither(16-bit ef2); Compressor → Limiter → PeakMeter; I2S TX ⇒ pins ⇒ I2S RX → Dither → I2S TX ⇒ pins ⇒ I2S RX | EQ magnitude within 0.3 dB of the design (0.2 measured), compressor static curve bit-exact vs the model and within 0.12 dB of the design, limiter holds a 0 dBFS tone at −0.96 dBFS (0 clips), 16-bit in-band THD+N ≤ −80 dB (−95 measured), I2S transport bit-exact |
| [AN011 — Pulse-Doppler radar](../doc/app_notes/an011_pulse_doppler_radar.md) | `pulse_doppler_radar.py` | RangeGate → PulseCompressor(Hamming chirp) → MTICanceller(3-pulse) → CornerTurn; DopplerProcessor(Hann) → CFAR2D → PeakExtractor → TargetList; AlphaBetaTracker | Pulse-Doppler chain on a synthetic scene: compressed peaks at the true ranges, MTI clutter suppression ≥ 30 dB, 3/3 targets per CPI with ≤ 3 false alarms and sub-bin centroids, confirmed tracks with range RMS ≤ 0.35 bin through dropped detections |
| [AN012 — Image pipeline](../doc/app_notes/an012_image_pipeline.md) | `image_pipeline.py` | Debayer → PixelGain → ColorMatrix(YCbCr) → {PixelHistogram | select Y → Kernel2D(Gaussian) → Sobel → Threshold → PixelHistogram} | Camera front end on a synthetic Bayer scene: YCbCr bit-exact vs the models (59 dB vs float), edge map bit-exact with 97 % float agreement, histograms = np.bincount, branch latency equals the declared sum, frame 2 == frame 1 under backpressure |
| [AN013 — Image pipeline](../doc/app_notes/an013_fsk_hamming_link.md) | `fsk_hamming_link.py` | GFSK + Hamming(7,4) + HDLC text link (AN013): framer, encoder and modulator RTL bit-exact against the composed models, RTL demodulator point on the model BER curve, corrected / uncorrectable passes | GFSK + Hamming(7,4) + HDLC text link (AN013): framer, encoder and modulator RTL bit-exact against the composed models, RTL demodulator point on the model BER curve, corrected / uncorrectable passes | GFSK + Hamming(7,4) + HDLC text link (AN013): framer, encoder and modulator RTL bit-exact against the composed models, RTL demodulator point on the model BER curve, corrected / uncorrectable passes |
| [AN009 — PMSM field-oriented control](../doc/app_notes/an009_foc_pmsm.md) | `foc_pmsm.py` | FOC (Clarke → Park → d/q PI → inverse Park → SVPWM) → PWM on a per-unit PMSM plant; ideal angle / QuadratureDecoder / SMO + AngleTracker sensorless | Speed loop settles within 2 % with all three sensors, \|i_d\| < 0.08 pu, encoder angle RMS < 3°, sensorless angle RMS < 10° after an open-loop start |

## Standalone core configs

YAML configurations for the standalone core generator (`litedsp_gen`), producing a Verilog core
with AXI-Stream data ports + AXI-Lite control port and the `csr.csv`/`csr.json`/`csr.h` register
map artifacts:

| Config | Chain | Generate |
|---|---|---|
| `ddc_core.yml` | NCO → Mixer(down) → FIR → Downsampler | `litedsp_gen examples/ddc_core.yml` |
| `qpsk_receiver_core.yml` | QPSK Costas → M&M timing recovery → hard decisions | `litedsp_gen examples/qpsk_receiver_core.yml` |
| `spectrum_core.yml` | Window(hann) → FFT → PSD | `litedsp_gen examples/spectrum_core.yml` |
| `foc_core.yml` | FOC current controller (abc currents + angle → duties) | `litedsp_gen examples/foc_core.yml` |
| `audio_core.yml` | Stereo TDM audio: AudioEQ → Compressor → Volume → Dither(16-bit) | `litedsp_gen examples/audio_core.yml` |
| `image_core.yml` | Camera front end: Debayer → PixelGain → RGB-to-YCbCr (pixel / pixel_rgb ports) | `litedsp_gen examples/image_core.yml` |
