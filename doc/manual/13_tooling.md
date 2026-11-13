# Flow, generator, GUI and host software {#tooling}

This chapter describes the tools around the blocks: the flow netlist that describes a chain, the
headless builder that turns it into gateware, the standalone core generator, the graphical
editor and the host software that drives a running chain.

Read it to assemble a chain without writing Migen, to deliver a chain to a non-LiteX design, or
to control a chain from a host.

## At a glance {#tool-glance}

| Tool | Command | Input | Output |
|------------------|----------------------------------|------------------|--------------------------|
| Flow generator | `litedsp_flow` | Netlist JSON | Chain Verilog |
| Standalone core | `litedsp_gen` | YAML file | Core Verilog, register map |
| Vivado packaging | `litedsp_gen` `--vivado-ip` | YAML file | IP-XACT package |
| Flow editor | `litedsp_gui` | Netlist JSON | Netlist, Verilog, live controls |
| Host commands | `litedsp_cli` | `csr.csv` of a SoC | Tuning, captures, spectrum |
| Datasheets | `litedsp.flow.docgen` | Block registry | `doc/blocks/` pages |

The four `litedsp_*` commands are console scripts of the package. All code generation is
headless and lives in `litedsp/flow/`: the command line tools, the tests and the editor call the
same functions, so the editor adds no generation logic of its own.

## The flow {#tool-flow}

The flow turns a graph of blocks into gateware. A *netlist* lists the blocks of a chain, their
parameters and the connections between their ports. The builder instantiates the blocks and
connects them; the IP core wraps the result with an AXI-Lite control port and AXI-Stream data
ports. The figure below shows the sources, the two generation paths and their outputs.

![The flow. A netlist, written by hand or saved by the editor, feeds the chain builder; a YAML
file names a netlist or holds one inline and feeds the IP core, which can be packaged for
Vivado.](tool_flow.svg)

The modules of `litedsp/flow/` split the work as the table below shows.

| Module | Role |
|------------------|------------------------------------------------------------------------|
| `metadata.py` | Reflects a block into a `BlockSpec`: parameters, ports, registers, latency |
| `registry.py` | The palette: every block the flow can build, with defaults and choices |
| `netlist.py` | JSON format, load and save, validation |
| `builder.py` | `LiteDSPFlowChain`: blocks as named submodules, top-level endpoints |
| `glue.py` | Automatic fan-out and delay balancing, loop rejection |
| `ipcore.py` | `LiteDSPFlowIPCore`: AXI-Lite to register bridge, register map export |
| `vivado.py` | IP Integrator wrapper, packaging and validation scripts |
| `generate.py` | `litedsp_flow`: netlist to chain Verilog |
| `docgen.py` | Per-block datasheets from the registry |

## Registry and reflection {#tool-registry}

The registry is the list of blocks the flow knows. Each entry gives a stable key (`nco`,
`fir_complex`), the block class, the default constructor arguments, a category, a display name
and the choices of string parameters.

The registry holds 229 blocks in 13 categories. Blocks that need constructor data a netlist
cannot express, such as the sample list of a replay block, are left out.

Reflection reads each block instead of describing it by hand. It builds the block once with its
registers enabled and records its constructor parameters, its stream ports and their layouts,
its registers and fields, its latency and its docstring.

The editor palette, the netlist validation, the generic host driver, the register appendix and
the datasheets use the reflection, so they follow the code; the typed drivers name their
registers explicitly and are covered by the tests.

The datasheets of `doc/blocks/` are generated from the reflection, one page per block plus an
index, with the recorded resource results of each block joined in. CI fails when they are stale.

```sh
# Regenerate doc/blocks/
python3 -m litedsp.flow.docgen
# Fail if doc/blocks/ is stale (CI)
python3 -m litedsp.flow.docgen --check
```

[Build options](#build-options) lists the constructor parameters of every block from the same
registry, and [Register reference](#registers) lists its registers.

## Netlist format {#tool-netlist}

A netlist is a JSON object. The example below is `litedsp/flow/examples/ddc.json`, a digital
down-converter: the input is mixed with a local oscillator, low-pass filtered and decimated.

```json
{
  "name": "ddc",
  "data_width": 16,
  "clock_ns": 10.0,
  "inputs":  [{"id": "rx_in",  "layout": "iq"}],
  "outputs": [{"id": "bb_out", "layout": "iq"}],
  "blocks": [
    {"id": "lo",   "type": "nco",         "params": {}},
    {"id": "mix",  "type": "mixer",       "params": {}},
    {"id": "lpf",  "type": "fir_complex",
     "params": {"n_taps": 33, "architecture": "pipelined"}},
    {"id": "deci", "type": "downsampler", "params": {}}
  ],
  "connections": [
    {"from": "rx_in",      "to": "mix.sink_a"},
    {"from": "lo.source",  "to": "mix.sink_b"},
    {"from": "mix.source", "to": "lpf.sink"},
    {"from": "lpf.source", "to": "deci.sink"},
    {"from": "deci.source","to": "bb_out"}
  ]
}
```

The keys are read by `litedsp/flow/netlist.py`; [Netlist keys](#opt-netlist) gives their
defaults. A block `id` becomes a submodule name and the prefix of the block's registers, so it
must be a lower-case identifier (`^[a-z][a-z0-9_]*$`). A port reference is
`<block_id>.<port>`, such as `mix.sink_a` or `split0.sources[0]`; a top-level port is referenced
by its bare `id`. A parameter left out of `params` takes its registry default.

The `layout` of a top-level port is a category, one of `iq`, `iq_symbol`, `real`, `tdm`, `abc`,
`angle`, `cell`, `target`, `track`, `pixel`, `pixel_rgb`, `video` or `raw`.

The builder takes the exact field widths, signedness and parameter fields from the block port
the top-level port connects to. A one-bit FEC stream or a timestamped I/Q stream can therefore
leave a chain without having the netlist `data_width`.

A `raw` top-level port must connect to a block port, from which its schema is taken. Two
destinations of one top-level input must have the same exact schema, not only the same
category; the builder rejects them otherwise.

### Validation {#tool-validation}

Loading a netlist into the builder validates it first and reports every problem at once. The
checks are the following:

- block ids are unique valid identifiers, distinct from the top-level port ids;
- every block type is a registry key, and every parameter is a parameter of that block;
- every top-level layout is one of the categories above;
- every connection goes from a source to a sink, between ports that exist, with the same layout
  category on both ends;
- no sink has two drivers: a raw fan-in is illegal, and two streams join through a block with
  distinct sinks, such as a combiner or a mixer.

Parameters that change a port layout, such as a channel count, are taken into account: the
block is reflected again with its netlist parameters before the layout checks.

## Chain builder {#tool-builder}

`LiteDSPFlowChain` instantiates a validated netlist. Each block becomes a submodule named after
its netlist `id`, so the register collection of LiteX prefixes every register with the block id:
the phase increment of block `lo` is `lo_phase_inc`.

The constructor arguments of a block are its registry defaults, overridden by the netlist
parameters. The netlist `data_width` is given to every block that takes one and does not set it.

The top-level ports become stream endpoints. `chain.endpoint("rx_in")` returns one by its id;
for a chain with a single input and a single output, `chain.sink` and `chain.source` alias them.
With `with_csr=True` (the default) every block exposes its registers; with `with_csr=False` the
chain is built for simulation or with hard-wired controls.

### Fan-out, loops and latency balancing {#tool-glue}

The stream contract has a single `ready` per source, so a source cannot drive two sinks
directly. When the netlist connects one source to several sinks, the builder inserts a split
that copies every beat to all its outputs. Feedback loops are rejected: the flow builds
feed-forward chains only, and a cycle in the block graph is reported with its path.

Every join is lock step: it pairs the k-th samples of its inputs whatever the latency of each
branch, but the shorter branch waits for the longer one, which lowers the throughput.

The builder therefore sums the latencies of the blocks along each branch, in samples, as each block
declares them ([Latency](#arch-latency)), and inserts an elastic delay of exactly the difference on
the shorter branch.

The inserted delays and splits copy the whole beat: payload, parameter fields, `first` and
`last`, whatever the layout. A delay deeper than 32 samples is built as a FIFO. A block that
declares no fixed latency (`None`, data dependent) counts as zero in the sum. With
`auto_delay=False`, nothing is inserted and every unbalanced join is reported as a warning.

The two example netlists show both insertions. In `fanout.json` a gain block feeds a DC blocker
and a combiner, and the DC blocker feeds the combiner too: the builder adds a split and a delay.
In `ddc.json`, the NCO declares a latency of one sample and the input none, so the input branch
of the mixer gets a one-sample delay.

```console
$ python3 -m litedsp.flow.generate litedsp/flow/examples/fanout.json --out build/fanout
Generated: [...]/build/fanout/fanout.v
  inserted glue: split_g_source, delay_sum_sinks_1
$ python3 -m litedsp.flow.generate litedsp/flow/examples/ddc.json --out build/ddc --csr
Generated: [...]/build/ddc/ddc.v
  inserted glue: delay_mix_sink_a
  CSRs: 37
```

The insertions depend on the netlist only, so a chain built twice is the same, and a netlist
chain is bit-identical to the same chain wired by hand with explicit delays. The YAML example
`examples/ddc_core.yml` carries the same one-sample delay as an explicit `delay` block.

## Standalone core {#tool-ipcore}

`LiteDSPFlowIPCore` wraps a chain for a design that does not use LiteX. It builds the chain with
its registers, adds an AXI-Lite slave and bridges it to the register banks, one bank per block
with registers, addressed as in a LiteX SoC. The figure below shows the core that `litedsp_gen`
makes from `examples/ddc_core.yml`.

![The standalone core. AXI-Lite accesses reach the register bank of each block through the
bridge; the top-level ports of the chain are the AXI-Stream ports of the core.](tool_ip.svg)

The data ports are the endpoints of the chain, whose signals already behave as AXI-Stream. Each
top-level port `<id>` becomes the signals of the table below. The registers are reached through
the `s_axil_*` port; the core runs on `sys_clk` with the synchronous reset `sys_rst`.

| Signal | AXI-Stream role |
|--------------------------|---------------------------------------------------|
| `<id>_valid` | `TVALID` |
| `<id>_ready` | `TREADY` |
| `<id>_last` | `TLAST` |
| `<id>_first` | First beat of a frame, no AXI-Stream equivalent |
| `<id>_payload_i`, `_q` | `TDATA` fields; other layouts carry their own fields |
| `<id>_payload_symbol` | Hard decision of a slicer (`iq_symbol` layout) |

The register banks are 2 KiB (`0x800`) apart, in alphabetical order of the block ids; read the
addresses from `csr.csv`. The AXI-Lite address is a byte address, 16 bits wide by default, and
the register data width is 32 bits. A block without registers, such as a delay, has no bank.

The core decodes only the low `axil_address_width` bits of the address, so `csr_base` must be a
multiple of `2**axil_address_width`, the window the core occupies in the system address map; the
core refuses another value with a `ValueError`. Without a `csr_base` key, the core takes the
`base_address` of the `csr` section of the netlist, 0 when the netlist has none.

The generator writes the files of the table below in its output directory. Software drives the
core from the register map; the block manifest lets the host drivers recognize each block
exactly (see [Host software](#tool-host)).

| File | Content |
|------------------------|------------------------------------------------------------|
| `<name>.v` | Verilog of the core |
| `*.init` | Initial contents of the ROMs, such as an NCO table |
| `csr.csv`, `csr.json` | Register map: bank bases, registers, addresses, access |
| `csr.h` | C addresses and accessors of the registers |
| `blocks.json` | Manifest: block id to registry key |

[Getting started](#gs-gen) runs the generator on `examples/ddc_core.yml` and shows its output.

### Vivado IP Integrator packaging {#tool-vivado}

IP Integrator needs canonical AXI4-Stream buses rather than the endpoint signals of the core.
With `--vivado-ip`, `litedsp_gen` writes a structural wrapper, `<name>_vivado`, and a Tcl script
that packages the wrapper, the core, the ROM files and the register map as an IP-XACT component
(`component.xml`). The wrapper maps the signals as follows:

- the payload fields are packed in layout order into `TDATA`, padded to whole bytes: I in the
  low half and Q in the high half for an I/Q stream, extra fields above, unused bits at zero;
- `first` goes to `TUSER[0]` and `last` to `TLAST`;
- inputs are named `s_axis_<id>_*` and outputs `m_axis_<id>_*`, the AXI4-Lite slave keeps its
  `s_axil_*` names, and the clock and reset are `aclk` and the active-low `aresetn`.

The clock, reset and bus interfaces are associated explicitly in the package instead of relying
on name inference, and the clock frequency comes from the netlist `clock_ns`. Packaging runs
Vivado in batch mode and fails without it; the script `package_ip.tcl` stays in the output
directory, to run later on a machine with Vivado.

`--vivado-validate` goes one step further. It instantiates the packaged core in a minimal block
design with every bus made external, validates the design and synthesizes its wrapper. This
catches catalog, interface and packaging errors that synthesis of the plain Verilog cannot see.
The default part is `xc7a200tsbg484-3`; `--vivado-part` selects another one. The AXI4-Lite ports
of the wrapper take their widths from the core, `axil_address_width` and `csr_data_width`.

```sh
# Package for IP Integrator
litedsp_gen examples/ddc_core.yml --output-dir build/ddc_core --vivado-ip
# Package, then instantiate and synthesize in a block design
litedsp_gen examples/ddc_core.yml --output-dir build/ddc_core --vivado-ip \
    --vivado-validate --vivado-part xcau20p-ffvb676-2-e
```

## Generator configuration {#tool-gen}

`litedsp_gen` reads a YAML file that holds the chain and the core options. The chain is either
inline under `flow:`, with the netlist keys, or a path under `netlist:` to a netlist JSON,
relative to the YAML file. Exactly one of the two must be present. The file below is
`examples/ddc_core.yml` without its header.

```yaml
# Core
name     : ddc_core
csr_base : 0x0

# Flow (or "netlist: ddc.json")
flow:
  name       : ddc
  data_width : 16
  clock_ns   : 10.0
  inputs     : [{id: rx_in,  layout: iq}]
  outputs    : [{id: bb_out, layout: iq}]
  blocks:
    - {id: lo,   type: nco,         params: {}}
    - {id: dly,  type: delay,       params: {depth: 1}}
    - {id: mix,  type: mixer,       params: {}}
    - {id: lpf,  type: fir_complex, params: {n_taps: 33, architecture: pipelined}}
    - {id: deci, type: downsampler, params: {}}
  connections:
    - {from: rx_in,       to: dly.sink}
    - {from: dly.source,  to: mix.sink_a}
    - {from: lo.source,   to: mix.sink_b}
    - {from: mix.source,  to: lpf.sink}
    - {from: lpf.source,  to: deci.sink}
    - {from: deci.source, to: bb_out}
```

The core options are `name`, `csr_base`, `axil_address_width` and `csr_data_width`; [YAML
keys](#opt-gen-yaml) gives their defaults. A number may be written as a string, in hexadecimal
for example. The `examples/` directory holds six configurations, from a DDC to an image front
end; [Standalone core configurations](#ex-configs) lists them.

## Flow editor {#tool-gui}

`litedsp_gui` is a node editor built on DearPyGui, installed with the `gui` extra of the
package. The left panel is the block palette, from the registry.

Each block is a node with one input per sink, one output per source and its parameters as
fields. The toolbar adds top-level ports, loads and saves netlists, and generates the chain
Verilog or the IP core through the flow.

The editor stores node positions in the `editor` section of the netlist, so a saved netlist
reopens as it was drawn; a hand-written netlist is laid out on a grid.

Each node shows the recorded resources and latency of its block, from `impl/budgets.json` of a
repository checkout, and the status bar sums them over the chain; an installed package has no
such file and shows no resources. A response window plots the quantized frequency
response of the selected filter node and follows its parameter edits.

In live mode, the Connect button opens a `litex_server` session on the `csr.csv` of a running
SoC and builds controls for every block it finds: NCO tuning in Hz, FIR tap reload, gain and
mixer settings, capture with a PSD plot.

In a SoC built from a netlist, the register prefixes are the netlist ids, so the live controls
line up with the editor nodes.

The graph and netlist logic of the editor and its live session are tested without a display
(`test/test_gui.py`); the rendering itself needs one.

## Host software {#tool-host}

`litedsp/software/drivers.py` holds the host drivers. A driver binds the registers
`<prefix>_<register>` of one block, through a LiteX `RemoteClient` or any bus object with the
same `regs` interface, and adds the unit conversions of that block. The table below lists the
main drivers of the RF families; the motor, audio, radar and image families have their own,
described in their chapters.

| Driver | Block | Adds |
|---------------------------------|------------------------|------------------------------------|
| `NCODriver` | NCO, NCO of a DDC or DUC | Frequency set and read in Hz |
| `FIRDriver` | FIR filters | Coefficient design and reload |
| `GainDriver` | Gain | Linear gain, bypass, saturation flag |
| `MixerDriver` | Mixer | Up or down mode, bypass |
| `CaptureDriver` | Capture | Threshold, forced trigger, armed and done |
| `CSRReaderDriver` | Register reader | Samples drained as complex numbers |
| `CaptureMemoryReader` | Capture memory window | Fast drain over the bus |
| `DMADriver` | DMA capture, replay | Base, length, enable, loop |
| `AGCDriver` | AGC | Target level, gain readback |
| `TimeCoreDriver` | Time core | Sample time read and set |
| `FECDecoderDriver` | Hamming, BCH decoders | Corrected and uncorrectable counts |

`discover()` finds the blocks of a SoC. Given the `blocks.json` manifest of a standalone core,
it is exact: each listed block gets its typed driver, or a generic driver built from the
registry reflection, with one accessor per register field. Without a manifest, it scans the
register names for the register sets of the drivers and keeps the most specific match.

`litedsp_cli` puts the drivers on the command line, over `litex_server`, and discovers the blocks
without a manifest. Start `litex_server` on the bridge of the board (UART, Ethernet or PCIe),
then run one of the commands below.

```sh
# List the LiteDSP blocks of the SoC
litedsp_cli info
# Tune an NCO, in Hz
litedsp_cli nco ddc_nco --freq -1e6
# Trigger a capture, print statistics, save the samples
litedsp_cli capture --samples 1024 --npy capture.npy
# Capture and print an ASCII spectrum
litedsp_cli spectrum --sample-rate 12.5e6
```

The capture commands need a capture block and a register reader in the SoC; `--capture` and
`--reader` select them by prefix when there are several. [Command line options](#opt-cli) lists
every option. The bench host scripts of [Benches](#boards) use the same drivers.

## Status {#tool-status}

`test/test_flow.py` checks the builder and the IP core against chains wired by hand, and CI
generates every YAML configuration of `examples/` ([Verification](#verification),
[status](#intro-status)).

Where to go next: [Getting started](#getting-started) runs the tools, [Integration](#integration)
puts a chain in a SoC or a Vivado design, [Build options](#build-options) lists every option.
