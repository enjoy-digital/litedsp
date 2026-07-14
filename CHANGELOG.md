# Changelog

All notable changes to LiteDSP are documented here. Versioning follows the LiteX ecosystem
calendar convention (`YYYY.MM`), synchronized with LiteX releases.

## [2026.07] - 2026-07

First release.

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
  CP insert/remove) are now registered in the flow/GUI palette (95 blocks total).

- Portable RF/DSP block toolbox, pure Migen/LiteX (no vendor IP): `generation/` (NCO/DDS,
  CORDIC, chirp, noise, replay, patterns), `mixing/` (mixer, DDC/DUC, DDC-bank and
  polyphase-filter-bank channelizers), `filter/`
  (FIR direct/symmetric/polyphase, CIC, halfband, IIR biquad, Hilbert, RRC pulse shaping,
  Farrow/rational/arbitrary resamplers, LMS equalizer, coefficient design), `rate/`, `level/`
  (gain, AGC, power, RMS, squelch, log/dB), `correction/` (DC offset, I/Q balance, CFO),
  `comm/` (FM/AM demod, PLL/Costas, coarse CFO estimator, timing recovery with M&M or Gardner
  TED, slicer, mapper,
  scrambler, CRC, convolutional encoder + hard/soft-decision Viterbi decoder,
  puncturer/depuncturer (DVB-S rates 2/3..7/8), OFDM cyclic prefix),
  `analysis/` (window, FFT/IFFT radix-2 SDF + iterative, PSD/Welch, magnitude, Goertzel,
  statistics, detectors), `stream/` (plumbing, CDC, capture, framing, Wishbone/LiteDRAM DMA)
  and `frontend/` (ADC/DAC interfaces, I/Q packetizers, LiteEth UDP streaming).
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
- Verification: per-block NumPy golden models (bit-exact or SNR-threshold, randomized
  backpressure) under `unittest`, Verilator co-simulation and lint sweep (`sim/`), Yosys/
  nextpnr + Vivado implementation gated on resource/fmax budgets (`impl/`), board-level
  benches on litex-boards targets (`bench/`).
- Quality characterization suite (`char/`): datasheet-grade metrics (SFDR/ENOB, ripple/
  attenuation, CIC droop error, image rejection, IMD3, AGC settling, window sidelobes)
  measured on the golden models and gated on direction-aware quality budgets
  (`char/budgets.json`), with a generated report (`doc/characterization.md`).
