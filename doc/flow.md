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
- **`registry.py`** — the palette: 117 blocks across 9 categories, with construction defaults and
  enumerated param choices. `registry.registry()` builds them all (cached).
- **`netlist.py`** — the tool-agnostic JSON format + load/save + validation (unknown
  type/port/param, layout mismatch, raw fan-in, duplicate/invalid ids).
- **`builder.py`** — `LiteDSPFlowChain`: instantiates each block as a *named submodule* (id = name, so
  `get_csrs()` auto-prefixes the whole register map), resolves port refs, exposes single-IO
  `.sink`/`.source`.
- **`glue.py`** — auto-inserts schema-preserving fan-out and reconvergent-path delays, and rejects
  combinational/feedback loops. Inserted glue copies the complete payload, parameter fields, and
  `first`/`last` markers rather than assuming a 16-bit I/Q stream.
- **`ipcore.py`** — `LiteDSPFlowIPCore`: AXI-Lite→CSR bridge over a `CSRBankArray` (one bank per block,
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

The JSON `layout` value (`iq`, `iq_symbol`, `real`, or `raw`) is a compatibility category. The
builder derives each top-level endpoint's concrete field widths, signedness, and parameter layout
from its connected block port. This permits, for example, one-bit FEC streams, wider statistic
records, FFT exponent parameters, and timestamped I/Q without pretending that every `real` or
`raw` port has the global `data_width`. A `raw` top-level port must therefore connect to a block
port from which its schema can be inferred. Fan-out destinations with the same category but
different concrete schemas are rejected before Verilog generation.

## Usage

```bash
# Chain Verilog:
litedsp_flow litedsp/flow/examples/ddc.json --out build/ddc

# Standalone core (AXI IP + csr.csv / csr.json / csr.h) from a YAML config (see litedsp/gen.py):
litedsp_gen examples/ddc_core.yml --output-dir build/ddc_core

# Vivado IP-Integrator package (component.xml + canonical AXI buses + driver artifacts):
litedsp_gen examples/ddc_core.yml --output-dir build/ddc_core --vivado-ip

# Also instantiate it in a block design and synthesize that wrapper for the selected part:
litedsp_gen examples/ddc_core.yml --output-dir build/ddc_core --vivado-ip --vivado-validate \
  --vivado-part xcau20p-ffvb676-2-e

# ...or directly from a netlist JSON:
python -c "from litedsp.flow.ipcore import generate_ip; generate_ip('litedsp/flow/examples/ddc.json','build/ddc_ip')"

# GUI editor (needs a display; DearPyGui):
litedsp_gui
```

The IP core exposes a `s_axil_*` AXI-Lite slave for configuration and, per top-level netlist I/O,
an AXI-Stream port (`<id>_valid`=tvalid, `<id>_ready`=tready, `<id>_last`=tlast,
`<id>_payload_i`/`_q`=tdata). The register map gives each block its own bank, e.g. `lo_phase_inc`,
`lpf_coeffs_coeff_0…` — write them over AXI-Lite at the addresses in `csr.csv`.
Top-level layout `iq_symbol` adds `<id>_payload_symbol[1:0]` for a QPSK slicer's hard decision.

With ``--vivado-ip``, the endpoint leaves are wrapped as canonical, byte-aligned AXI4-Stream
interfaces. I/Q occupies the low/high halves of ``TDATA``; additional payload fields follow in
layout order, unused high bits are zero, ``first`` maps to ``TUSER[0]``, and ``last`` maps to
``TLAST``. The package includes ``component.xml``, synthesizable HDL and ROM initialization
files, XGUI metadata, ``csr.csv/json/h`` and ``blocks.json``. Its AXI4-Lite, stream, clock and
active-low reset interfaces are associated explicitly rather than relying on name inference.

## Status / roadmap

- Phase 1 (headless netlist → chain Verilog) and Phase 2 (AXI IP core + register map) are done and
  tested (`test/test_flow.py`): netlist-assembled chains are bit-identical to hand-wired
  equivalents, and an AXI-Lite write at a mapped address reaches the right block's CSR in
  simulation.
- Phase 3 (DearPyGui editor, `litedsp/gui/`) is functional; its pure graph↔netlist logic is tested
  (`test/test_gui.py`), the rendering needs a display.
- Live mode: the editor's Connect button opens a litex_server session on the SoC's `csr.csv`
  (`litedsp/gui/live.py` + `litedsp/software/drivers.py`) and exposes runtime controls (NCO
  tuning, FIR reload, capture + PSD plot) for every discovered block — netlist block ids are
  the register prefixes, so live controls line up with editor nodes.
- Latency balancing on reconvergent paths is automatic: unequal-latency joins get an exact
  schema-preserving elastic delay inserted (reported in `flow_inserted`); `auto_delay=False`
  restores warn-only behavior. Analysis reads the instantiated block's selected latency, so an
  architecture/depth parameter that differs from the palette default is aligned correctly.
- Automatic fan-out and alignment support I/Q, real, symbol/FEC, arbitrary raw payloads, and
  stream parameter fields. Randomized-stall regressions cover framed 9-bit real reconvergence and
  timestamp-param fan-out, including exact `first`/`last` preservation.
- Load/Save round-trips the canvas: node positions are stored in the netlist's `editor`
  section (ignored by codegen) and restored on load, with a grid fallback for hand-written
  netlists.
- Vivado IP-Integrator packaging is generated and integrity-checked from the same core/netlist;
  the DDC and QPSK receiver examples exercise 32-bit I/Q and byte-padded I/Q+symbol streams.
  ``--vivado-validate`` additionally makes every bus external in a minimal block design, runs
  ``validate_bd_design`` and synthesizes the generated wrapper, catching catalog, interface and
  packaged-source errors that standalone HDL synthesis cannot see.
