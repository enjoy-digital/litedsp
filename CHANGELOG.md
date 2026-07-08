# Changelog

All notable changes to LiteDSP are documented here. Versioning follows the LiteX ecosystem
conventions (SemVer-ish, `YYYY.MM`-friendly tags may be adopted once aligned with LiteX releases).

## [Unreleased]

### Added
- `CONTRIBUTING.md` (new-block checklist, tests, commit conventions) and `doc/resources.md` —
  a per-block LUT/FF/BRAM/DSP + Fmax table generated from the implementation budgets
  (`python3 impl/report.py`).
- Multi-sample-per-cycle (parallel) datapaths for rates above the fabric clock:
  `iq_layout`/`real_layout` gain an `n_samples` lane dimension (+ `iq_lanes`/`real_lanes`
  helpers), with `IQSerialToParallel`/`IQParallelToSerial` adapters and the first parallel
  blocks — `ParallelNCO`, `ParallelMixer`, `ParallelFIRFilter` — each bit-identical to its
  serial counterpart on the flattened lane stream.
- GUI live mode: Connect opens a litex_server session on the SoC's `csr.csv`
  (`litedsp/gui/live.py`) and builds runtime controls for every discovered block — NCO tuning
  in Hz, FIR tap reload, capture trigger with an in-editor PSD plot.
- `litedsp/software/`: host-side Python drivers over litex_server (`RemoteClient`) — tune NCOs
  in Hz, reload FIR taps, trigger/drain captures to NumPy, run DMA windows — with register-map
  auto-discovery, plus the `litedsp_cli` entry point (`info`/`nco`/`capture`/`spectrum`).
- `bench/`: board-level proof points (LiteX-ecosystem style) — `spectrum.py` builds a
  tone+AWGN → DDC → Capture SoC with UARTBone on litex-boards targets (Arty,
  Colorlight 5A-75B), `test_spectrum.py` drives it from the host and checks the PSD peak;
  CI elaborates every bench board.
- `IQAdd` (saturating complex adder) and `CSRReader` (bus-paced buffer readout) stream blocks.
- `litedsp/frontend/`: boundary adapters — `ADCInterface`/`DACInterface` (raw converter words
  <-> Q1.(N-1) streams), `IQPacketizer`/`IQDepacketizer` (framed wide-word host-link glue for
  LitePCIe DMA & co), `UDPIQStreamer`/`UDPIQReceiver` (I/Q sample packets over LiteEth UDP).
- IRQ support (`with_irq=True`, LiteX `EventManager`) on trigger-type blocks: `Squelch`
  (gate opened/closed), `EnergyDetector` (signal detected), `Capture` (buffer ready — also new
  `done` status), `AGC` (gain railed — also new `railed` status), so software no longer polls.
- `litedsp/stream/dma.py`: `DMACapture`/`DMAReplay` — sustained-rate capture/replay of I/Q
  streams to/from memory over Wishbone DMA (`litex.soc.cores.dma`) or LiteDRAM native-port DMA
  (`litedram.frontend.dma`), with the standard base/length/enable/done/loop register set.
- `litedsp/gen.py`: standalone core generator in the LiteX-ecosystem style (`litedsp_gen
  config.yml` → Verilog core with AXI-Stream data + AXI-Lite control + `csr.csv`/`csr.json`/
  `csr.h`), with `examples/ddc_core.yml`.
- Console scripts: `litedsp_gen`, `litedsp_flow`, `litedsp_gui`.
- `doc/litex_integration.md`: integrating blocks/chains in a LiteX SoC and in non-LiteX flows.

### Changed
- Verilog emission helper moved into the package (`litedsp/verilog.py`); `sim/verilog.py` is a
  compatibility shim.
- GUI moved into the package (`gui/` → `litedsp/gui/`); run it with `litedsp_gui`.

## [0.1.0] - 2026-07

Initial release: portable RF/DSP block toolbox (generation, mixing, filter, rate, level,
correction, comm, analysis, stream), golden-model test harness, Verilator co-simulation,
FPGA implementation budgets (ECP5/Artix-7), flow netlist → Verilog/CSR/AXI IP generation and
DearPyGui flow editor.
