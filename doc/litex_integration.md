# Integrating LiteDSP in a LiteX SoC

LiteDSP blocks are plain `LiteXModule`s with `stream.Endpoint` interfaces, so they integrate in a
LiteX SoC exactly like any LiteX core: instantiate, connect streams, and the CSRs are collected
automatically. This document shows the three integration levels, from "a block in my SoC" to
"a standalone Verilog core in a non-LiteX flow".

## 1. Blocks inside a LiteX SoC (the native way)

Add a block (or a composite like `DDC`) as a submodule of your SoC; with `with_csr=True`
(the default) its configuration/status registers appear in the SoC CSR map under the
attribute name, and are then accessible from software (`csr.h`), `litex_server`, etc.:

```python
from litedsp.mixing.ddc import DDC

class MySoC(SoCCore):
    def __init__(self, platform, **kwargs):
        SoCCore.__init__(self, platform, **kwargs)

        # DDC: NCO tuning + complex down-mix + /8 CIC decimation, controlled over CSR.
        self.ddc = DDC(data_width=16, decimation=8)
        self.comb += [
            adc.source.connect(self.ddc.sink),      # Any iq_layout stream source.
            self.ddc.source.connect(dma.sink),      # Any iq_layout stream sink.
        ]
```

Conventions (see `interfaces.md` for the full contract):

- Streams are LiteX `stream.Endpoint`s (`sink`/`source`) with full `valid`/`ready` backpressure;
  connect them with `connect()`.
- With `with_csr=False`, the parent drives the control `Signal`s directly instead — this is how
  composites (DDC/DUC) wire their sub-blocks and how a design can hard-configure a block.
- Blocks are `@ResetInserter()`-wrapped: drive `block.reset` for a per-block synchronous reset.

## 2. Flow netlists (chains) inside a LiteX SoC

A whole processing chain described as a flow netlist (JSON, written by hand or with the
`litedsp_gui` editor) can be instantiated in a SoC through `FlowChain`; each block's CSRs are
prefixed by its netlist id:

```python
from litedsp.flow.builder import FlowChain
from litedsp.flow import netlist

class MySoC(SoCCore):
    def __init__(self, platform, **kwargs):
        SoCCore.__init__(self, platform, **kwargs)
        self.chain = FlowChain(netlist.load("rx_chain.json"), with_csr=True)
        # Top-level netlist I/Os are endpoints: chain.endpoint("rx_in"), chain.endpoint("bb_out"),
        # aliased to chain.sink / chain.source for single-input/single-output chains.
```

## 3. Standalone core (non-LiteX flows)

For a traditional Verilog/Vivado flow, generate a standalone core with AXI-Stream data ports and
an AXI-Lite control port from a YAML config:

```bash
litedsp_gen examples/ddc_core.yml --output-dir build
```

This produces the core Verilog plus the register map artifacts (`csr.csv`, `csr.json`, `csr.h`)
to drive it from software. See `litedsp/gen.py` and `flow.md` for the config/netlist schema.

## Software access

CSR fields are documented in the generated register map. Inside a LiteX SoC, the registers are
reachable through the usual paths: generated `csr.h` accessors for firmware, and
`litex_server`/`RemoteClient` for host-side control (UART/Ethernet/PCIe bridges).

## Installation

```bash
pip install -e .   # from the repository, or:
litex_setup --init --install   # once litedsp is registered in litex_setup repos.
```
