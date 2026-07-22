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
| [AN006 — ADS-B / Mode-S receiver](../doc/app_notes/an006_adsb_receiver.md) | `adsb_receiver.py` | 2 MHz magnitude → Correlator(8 us preamble) → PPM early/late decision | Exact frame acquisition and zero errors across a noisy 112-bit DF17 frame |
| [AN007 — AIS GMSK receiver](../doc/app_notes/an007_ais_receiver.md) | `ais_receiver.py` | GMSK/CFO/AWGN → FMDemod → integrate/dump → NRZI → training/FCS | Exact training acquisition, zero payload errors, and valid X.25 FCS |
| [AN008 — Chirp spread-spectrum receiver](../doc/app_notes/an008_css_receiver.md) | `css_receiver.py` | CSS upchirp → dechirp → fixed-point FFT → peak bin | Exact SF7 symbol recovery with a ≥12 dB FFT-bin margin under noise and CFO |

## Standalone core configs

YAML configurations for the standalone core generator (`litedsp_gen`), producing a Verilog core
with AXI-Stream data ports + AXI-Lite control port and the `csr.csv`/`csr.json`/`csr.h` register
map artifacts:

| Config | Chain | Generate |
|---|---|---|
| `ddc_core.yml` | NCO → Mixer(down) → FIR → Downsampler | `litedsp_gen examples/ddc_core.yml` |
| `qpsk_receiver_core.yml` | QPSK Costas → M&M timing recovery → hard decisions | `litedsp_gen examples/qpsk_receiver_core.yml` |
| `spectrum_core.yml` | Window(hann) → FFT → PSD | `litedsp_gen examples/spectrum_core.yml` |
