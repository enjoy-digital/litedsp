# Changelog

All notable changes to LiteDSP are documented here. Versioning follows the LiteX ecosystem
conventions (SemVer-ish, `YYYY.MM`-friendly tags may be adopted once aligned with LiteX releases).

## [Unreleased]

### Added
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
