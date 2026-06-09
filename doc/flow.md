# LiteDSP Flow — block-graph → Verilog + CSR map + AXI IP core

`litedsp/flow/` turns a graph of LiteDSP blocks into gateware: assemble a chain from a JSON
*netlist* (by hand, by script, or from the DearPyGui editor) and generate the chain Verilog, a CSR
register map, and an integratable **AXI-Stream + AXI-Lite** IP core. The GUI is a thin front-end;
all code generation is headless and reused identically by the CLI, tests, and the editor.

## Pipeline

```
 netlist.json ──▶ FlowChain (builder) ──▶ Verilog            (flow.generate)
              └─▶ FlowIPCore (ipcore)  ──▶ Verilog + csr.csv/json/h  (flow.ipcore.generate_ip)
```

- **`metadata.py`** — reflects each block into a `BlockSpec` (params from the constructor
  signature, stream ports + payload layouts from a built instance, CSRs from `get_csrs()`).
- **`registry.py`** — the palette: ~88 blocks across 9 categories, with construction defaults and
  enumerated param choices. `registry.registry()` builds them all (cached).
- **`netlist.py`** — the tool-agnostic JSON format + load/save + validation (unknown
  type/port/param, layout mismatch, raw fan-in, duplicate/invalid ids).
- **`builder.py`** — `FlowChain`: instantiates each block as a *named submodule* (id = name, so
  `get_csrs()` auto-prefixes the whole register map), resolves port refs, exposes single-IO
  `.sink`/`.source`.
- **`glue.py`** — auto-inserts `Split` for fan-out, rejects combinational/feedback loops, and
  *reports* reconvergent latency imbalance (insert an explicit `delay` block to fix — kept
  non-mutating so generated chains are predictable and bit-identical to hand-wired ones).
- **`ipcore.py`** — `FlowIPCore`: AXI-Lite→CSR bridge over a `CSRBankArray` (one bank per block,
  addressed exactly as LiteX/SoCMini) + the chain's AXI-Stream-compatible data ports.

## Netlist format

```json
{
  "name": "ddc", "data_width": 16, "clock_ns": 10.0,
  "inputs":  [{"id": "rx_in",  "layout": "iq"}],
  "outputs": [{"id": "bb_out", "layout": "iq"}],
  "blocks": [
    {"id": "lo",  "type": "nco",         "params": {}},
    {"id": "mix", "type": "mixer",       "params": {}},
    {"id": "lpf", "type": "fir_complex", "params": {"n_taps": 33}}
  ],
  "connections": [
    {"from": "rx_in",     "to": "mix.sink_a"},
    {"from": "lo.source", "to": "mix.sink_b"},
    {"from": "mix.source","to": "lpf.sink"},
    {"from": "lpf.source","to": "bb_out"}
  ]
}
```
Port refs are `"<block_id>.<port>"` (e.g. `mix.sink_a`, `split0.sources[0]`); top-level I/O are
referenced by their bare id. See `litedsp/flow/examples/`.

## Usage

```bash
# Chain Verilog:
python -m litedsp.flow.generate litedsp/flow/examples/ddc.json --out build/ddc

# AXI IP core + register map (csr.csv / csr.json / csr.h):
python -c "from litedsp.flow.ipcore import generate_ip; generate_ip('litedsp/flow/examples/ddc.json','build/ddc_ip')"

# GUI editor (needs a display; DearPyGui):
python -m gui.app
```

The IP core exposes a `s_axil_*` AXI-Lite slave for configuration and, per top-level netlist I/O,
an AXI-Stream port (`<id>_valid`=tvalid, `<id>_ready`=tready, `<id>_last`=tlast,
`<id>_payload_i`/`_q`=tdata). The register map gives each block its own bank, e.g. `lo_phase_inc`,
`lpf_coeffs_coeff_0…` — write them over AXI-Lite at the addresses in `csr.csv`.

## Status / roadmap

- Phase 1 (headless netlist → chain Verilog) and Phase 2 (AXI IP core + register map) are done and
  tested (`test/test_flow.py`): netlist-assembled chains are bit-identical to hand-wired
  equivalents, and an AXI-Lite write at a mapped address reaches the right block's CSR in
  simulation.
- Phase 3 (DearPyGui editor, `gui/`) is functional; its pure graph↔netlist logic is tested
  (`test/test_gui.py`), the rendering needs a display.
- Next: in-canvas netlist *load* (round-trip positions), optional auto-`Delay` balancing on
  reconvergent paths, and packaging the IP for Vivado IP-integrator.
