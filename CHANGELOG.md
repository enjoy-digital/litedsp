# Changelog

All notable changes to LiteDSP are documented here. Versioning follows the LiteX ecosystem
calendar convention (`YYYY.MM`), synchronized with LiteX releases.

## [2026.07] - 2026-07

First release.

- Portable RF/DSP block toolbox, pure Migen/LiteX (no vendor IP): `generation/` (NCO/DDS,
  CORDIC, chirp, noise, replay, patterns), `mixing/` (mixer, DDC/DUC, channelizer), `filter/`
  (FIR direct/symmetric/polyphase, CIC, halfband, IIR biquad, Hilbert, RRC pulse shaping,
  Farrow/rational/arbitrary resamplers, LMS equalizer, coefficient design), `rate/`, `level/`
  (gain, AGC, power, RMS, squelch, log/dB), `correction/` (DC offset, I/Q balance, CFO),
  `comm/` (FM/AM demod, PLL/Costas, timing recovery with M&M or Gardner TED, slicer, mapper,
  scrambler, CRC, convolutional encoder + hard-decision Viterbi decoder, OFDM cyclic prefix),
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
