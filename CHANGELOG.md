# Changelog

All notable changes to LiteDSP are documented here. Versioning follows the LiteX ecosystem
conventions (SemVer-ish, `YYYY.MM`-friendly tags may be adopted once aligned with LiteX releases).

## [Unreleased]

### Added
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
