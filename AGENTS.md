# AGENTS.md: LiteDSP

Portable RF/DSP building blocks for FPGAs (Migen/LiteX, no vendor IP): filters, mixing, rate
change, level, correction, analysis, flow-graph generation. Work in progress: APIs can still move.

Read the LiteX agent page first: https://github.com/enjoy-digital/litex/wiki/LiteX-for-AI-Agents (framework map, conventions, how to
verify a change, contribute back). Index of the whole wiki for agents: https://github.com/enjoy-digital/litex/wiki/llms.txt.

## Where things are

- `litedsp/`: block families (`filter/`, `mixing/`, `rate/`, `level/`, `correction/`, `analysis/`, `comm/`, `stream/`, `flow/`...), `gen.py` (`litedsp_gen`), `flow/` (`litedsp_flow`), `gui/`, `software/` (`litedsp_cli`).
- `sim/`: Verilator co-simulation and lint (`sim/run_lint.py`); `examples/`, `bench/`, `impl/`; `test/`.

## Verify a change

```sh
python3 -m unittest discover -s test -v                            # unit tests (CI runs them in shards)
python3 sim/run_lint.py                                             # Verilator lint of all registry blocks
```

- A passing Migen simulation does not prove the Verilog: give intermediates (sums, shifts, products)
  explicit widths and run the Verilator co-simulation.
- A serial block's `sink.ready` must not depend on `sink.valid` (combinational loops).
- Per-beat controls must travel with their beat through the pipeline.

## Rules

- Style: https://github.com/enjoy-digital/litex/blob/master/doc/coding_style.md (match the
  surrounding file; `module: Description of the change.` commit titles; one change per commit).
- Never edit generated files (`build/`, `csr.h`, `csr.csv`, the Verilog): change the Python.
- One topic per pull request, from the default development branch, with what was tested and on
  which hardware; say that an agent wrote it and who supervised. Do not rename options or
  reformat unrelated code.
- Hardware: never flash a board or write its SPI flash unless the user asked; `--load` (volatile)
  is the default for experiments.

## Debug on hardware

Method: https://github.com/enjoy-digital/litex/wiki/Debug-A-SoC-On-Hardware (check the link and `--ident` first, registers before
traces, narrow LiteScope captures). `litex_mcp` gives the same loop as MCP tools (CSRs by name,
LiteScope captures, builds with parsed timing, simulation): https://github.com/enjoy-digital/litex/wiki/LiteX-for-AI-Agents#drive-a-soc-through-mcp.
