# Changelog

All notable changes to LiteDSP are documented here. Versioning follows the LiteX ecosystem
calendar convention (`YYYY.MM`), synchronized with LiteX releases.

## [2026.07] - 2026-07

Initial development release. LiteDSP remains work in progress; APIs and block interfaces may
still change before the first stable release.

### API conventions (pre-release breaking changes)

Parameter naming was harmonized across the library before the first release (no aliases kept):

| Block | Old | New |
|---|---|---|
| `LiteDSPFIRDecimator` | `(n_taps, R)` positional | `n_taps=32, decimation=8` |
| `LiteDSPFIRInterpolator` | `(n_taps, L)` positional | `n_taps=32, interpolation=8` |
| `LiteDSPCICDecimator` / `Interpolator` / parallel | `R=, N=, M=` | `decimation=`/`interpolation=`, `n_stages=`, `diff_delay=` |
| `LiteDSPCICDecimatorRuntime` | `N=, M=` | `n_stages=`, `diff_delay=` |
| `LiteDSPDecimator` / `LiteDSPInterpolator` | `factor=`, `stages=` | `decimation=`/`interpolation=`, `n_stages=` |
| `LiteDSPRationalResampler` | `(L, M)` positional | `interpolation=3, decimation=2` |
| `LiteDSPArbResampler` | `ratio_int=` | `ratio_int_bits=` (it is a width) |
| `LiteDSPIIRBiquad` | `coeffs=` | `coefficients=` (`sections=` stays on the cascade: SOS list) |
| `LiteDSPScrambler` / `Descrambler` | `taps=` | `polynomial=` |
| `LiteDSPPSD` | `latency=` (required) | `fft_latency=None` (defaults to `N-1`) |

Additional contracts introduced with the harmonization:
- Every processing block declares `self.latency` (a number, or an explicit `None` for
  data-dependent blocks); enforced by `test/test_metadata_policy.py`.
- In-line layout-preserving blocks (filter/correction/level) expose a boolean `self.bypass`
  (delay-matched passthrough via `litedsp.common.add_bypass`); verified by `test/test_bypass.py`.
- Constructors raise `ValueError` with an actionable message on invalid parameters
  (`litedsp.common.check`); validation survives `python -O`.
- The coding/FEC and OFDM blocks (scrambler, CRC, convolutional encoder, Viterbi decoder,
  CP insert/remove) are now registered in the flow/GUI palette (114 blocks total).

- Portable RF/DSP block toolbox, pure Migen/LiteX (no vendor IP): `generation/` (NCO/DDS,
  CORDIC, chirp, noise, replay, patterns), `mixing/` (mixer, DDC/DUC, DDC-bank and
  polyphase-filter-bank channelizers), `filter/`
  (FIR direct/symmetric/polyphase, CIC, halfband, IIR biquad, Hilbert, RRC pulse shaping,
  Farrow/rational/arbitrary resamplers, LMS equalizer, coefficient design), `rate/`, `level/`
  (gain, AGC, CFR, power, RMS, squelch, log/dB), `correction/` (DC offset, I/Q balance, CFO),
  `comm/` (FM/AM demod, PLL/BPSK Costas/QPSK decision-directed carrier recovery, coarse CFO
  estimator, timing recovery with M&M or Gardner
  TED, slicer, mapper,
  scrambler, CRC, convolutional encoder + hard/soft-decision Viterbi decoder,
  puncturer/depuncturer (DVB-S rates 2/3..7/8), Reed-Solomon RS(255, k) encoder + decoder,
  OFDM cyclic prefix + OFDM equalizer with LS
  channel estimation, divider-free one-tap correction and per-bin CSI output),
  `analysis/` (window, FFT/IFFT radix-2 SDF + iterative, PSD/Welch, magnitude, Goertzel,
  statistics, detectors), `stream/` (plumbing, CDC, capture, framing, Wishbone/LiteDRAM DMA)
  and `frontend/` (ADC/DAC interfaces, I/Q packetizers, LiteEth UDP streaming).
- Reed-Solomon RS(255, k) codec over GF(2^8) (`litedsp/comm/rs.py`): systematic LFSR encoder
  and full hard-decision decoder (syndromes, serial Berlekamp-Massey, Chien search, Forney
  magnitudes), t = (n - k)/2 configurable from 1 to 16 (RS(255,223) default), corrected-symbol
  and uncorrectable-block status CSRs, bit-exact golden models including status. Conventional
  basis (field polynomial 0x11D, fcr = 0); CCSDS 131.0-B dual-basis (0x187) conversion is a
  documented follow-up.
- Block interleaver/deinterleaver (`litedsp/comm/interleaver.py`, `LiteDSPBlockInterleaver`/
  `LiteDSPBlockDeinterleaver`): CCSDS-style depth-I byte interleaving between the RS and
  convolutional layers (rows x cols transpose, write row-wise / read column-wise), ping-pong
  block RAM for gapless back-to-back streaming (1 symbol/cycle), framed output blocks,
  bit-exact golden models. Demonstrated by the CCSDS concatenated-FEC telemetry app note
  (AN005, `examples/ccsds_telemetry.py`): RS(255,223) x I -> interleave -> conv K=7 -> QPSK/
  AWGN + jammer burst -> soft Viterbi -> deinterleave -> RS decode, with a burst-length sweep
  showing the ~I-times correctable-burst gain and a full RTL end-to-end recovery run.
- LDPC codec for the IEEE 802.11n rate-1/2 n=648 (z=27) quasi-cyclic code (`litedsp/comm/
  ldpc.py`, `LiteDSPLDPCEncoder`/`LiteDSPLDPCDecoder`): back-substitution encoder over the
  dual-diagonal parity structure (no dense generator, ~650 flops of XOR network, H*c^T = 0
  verified against the expanded parity-check matrix), row-layered normalized min-sum decoder
  (factor 0.75 = x - (x >> 2), 4-bit input LLRs, compressed min1/min2/index/signs check
  messages, APP + check-message block RAMs, circulant-shift addressing) with early
  termination on a clean syndrome and iteration/parity/failure status CSRs. Bit-exact golden
  models including iteration counts; measured quantized waterfall BER 9.8e-3 @ 2.0 dB /
  6.7e-4 @ 2.5 dB / < 2.6e-6 @ 3.0 dB Eb/N0 (BPSK, AWGN, 8 iterations). One LLR per beat;
  the optional z-parallel QC datapath evaluates all 27 lifted rows together with lane-banked
  APP/check state, staged cyclic rotations and an overlapped write pipe (4,708 worst-case
  clocks/block; bit-exact with the serial decoder/model).
- Digital predistortion actuator (`litedsp/level/dpd.py`, `LiteDSPDPD`): memory-polynomial-lite
  per-tap complex-gain LUTs on delayed samples (Q2.frac entries, two-region alpha-max-beta-min
  magnitude binning, identity reset = exact passthrough, sequential CSR LUT reload with tap
  select, fixed 3-cycle latency, bypass). Adaptation is host-side, as in deployed DPD systems:
  `litedsp/software/dpd.py` provides `DPDAdapter` (indirect-learning least squares on the
  LUT-bin basis, gateware-exact binning, Q2.frac quantization) plus a `simulate_pa()` Saleh +
  memory PA model, programmed through `DPDDriver`. Closed-loop test gates >= 10 dB ACLR
  improvement on the synthetic PA (typically +15 dB ACLR / +25 dB EVM); actuator verified
  bit-exact against `dpd_model` under backpressure, random LUT contents and mock-bus-programmed
  fitted LUTs.
- Crest-factor reduction (`litedsp/level/cfr.py`, `LiteDSPCFR`): peak-cancellation CFR —
  local-max peak detection on the alpha-max-beta-min magnitude estimate against a runtime
  threshold, divider-free correction coefficient `g = (|x_pk| - T)/|x_pk|` (leading-zero
  normalization + 64-entry midpoint reciprocal LUT, ~0.8% max error), and a unit-peak
  windowed-sinc cancellation pulse subtracted from the delay-matched stream (single pulse
  engine; peaks arriving while busy pass uncorrected and are counted). Runtime threshold /
  bypass, corrected/uncorrected peak counter CSRs; bit-exact `cfr_model` including counters;
  characterized PAPR reduction + below-threshold EVM gates (`char/`, ~1.9 dB PAPR reduction
  at a 7 dB target on ~11 dB-PAPR OFDM-like stimulus, EVM ~1.6%, out-of-band regrowth
  bounded).
- Multi-sample-per-cycle (parallel) datapaths for rates above the fabric clock — parallel
  NCO/mixer/FIR/CIC/DDC, bit-identical to their serial counterparts.
- All public hardware classes carry the `LiteDSP` prefix (`LiteDSPNCO`, `LiteDSPFIRFilter`,
  ...), following the LiteX ecosystem naming convention.
- Standardized interfaces: LiteX `stream.Endpoint` with full valid/ready backpressure, uniform
  `with_csr`/`add_csr()` control, `bypass`, exposed `latency`; parameterized Qm.n fixed-point
  with shared rounding/saturation/scaling helpers. IRQ support (`with_irq=True`) on
  trigger-type blocks (squelch, energy detector, capture, AGC).
- Tooling: `litedsp_flow` (JSON netlist → chain Verilog + CSR map + AXI-Stream/AXI-Lite IP
  core), `litedsp_gui` (DearPyGui node editor with live mode over litex_server), `litedsp_gen`
  (YAML → standalone Verilog core + `csr.csv`/`csr.json`/`csr.h`, see `examples/*.yml`) and
  `litedsp_cli` (host-side drivers: NCO tuning in Hz, FIR tap reload, captures to NumPy).
- Verification: NumPy golden models (bit-exact or SNR-threshold, randomized backpressure)
  under `unittest`, 45 Verilator co-simulation configurations and a full-registry lint sweep
  (`sim/`), Yosys/
  nextpnr + Vivado implementation gated on resource/fmax budgets (`impl/`), board-level
  benches on litex-boards targets (`bench/`), SymbiYosys formal verification of the stream
  fabric — no sample loss/duplication under arbitrary backpressure, payload stability while
  stalled, no valid-from-nowhere (`formal/`, see `doc/formal.md`).
- Quality characterization suite (`char/`): datasheet-grade metrics (SFDR/ENOB, ripple/
  attenuation, CIC droop error, image rejection, IMD3, AGC settling, window sidelobes)
  measured on the golden models and gated on direction-aware quality budgets
  (`char/budgets.json`), with a generated report (`doc/characterization.md`).
