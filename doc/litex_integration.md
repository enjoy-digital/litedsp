# Integrating LiteDSP in a LiteX SoC

LiteDSP blocks are plain `LiteXModule`s with `stream.Endpoint` interfaces, so they integrate in a
LiteX SoC exactly like any LiteX core: instantiate, connect streams, and the CSRs are collected
automatically. This document shows the three integration levels, from "a block in my SoC" to
"a standalone Verilog core in a non-LiteX flow".

## 1. Blocks inside a LiteX SoC (the native way)

Add a block (or a composite like `LiteDSPDDC`) as a submodule of your SoC; with `with_csr=True`
(the default) its configuration/status registers appear in the SoC CSR map under the
attribute name, and are then accessible from software (`csr.h`), `litex_server`, etc.:

```python
from litedsp.mixing.ddc import LiteDSPDDC

class MySoC(SoCCore):
    def __init__(self, platform, **kwargs):
        SoCCore.__init__(self, platform, **kwargs)

        # DDC: NCO tuning + complex down-mix + /8 CIC decimation, controlled over CSR.
        self.ddc = LiteDSPDDC(data_width=16, decimation=8)
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
`litedsp_gui` editor) can be instantiated in a SoC through `LiteDSPFlowChain`; each block's CSRs are
prefixed by its netlist id:

```python
from litedsp.flow.builder import LiteDSPFlowChain
from litedsp.flow import netlist

class MySoC(SoCCore):
    def __init__(self, platform, **kwargs):
        SoCCore.__init__(self, platform, **kwargs)
        self.chain = LiteDSPFlowChain(netlist.load("rx_chain.json"), with_csr=True)
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

## Getting samples in and out

`litedsp/frontend/` holds the boundary adapters:

- **Converters**: `LiteDSPADCInterface` / `LiteDSPDACInterface` adapt raw converter words (two's-complement or
  offset-binary, any resolution ≤ `data_width`) to the chain's left-aligned Q1.(N-1) streams.
- **Memory**: `litedsp/stream/dma.py` `LiteDSPDMACapture` / `LiteDSPDMAReplay` move streams to/from memory over
  Wishbone DMA or a LiteDRAM native port (`soc.sdram.crossbar.get_port()`).
- **Ethernet**: `LiteDSPUDPIQStreamer` / `LiteDSPUDPIQReceiver` send/receive fixed-size UDP sample packets
  through a LiteEth UDP core.
- **PCIe (or any tlast DMA)**: `LiteDSPIQPacketizer` / `LiteDSPIQDepacketizer` produce/consume a framed
  `data`+`last` word stream that connects directly to a LitePCIe DMA endpoint:

```python
self.packetizer = IQPacketizer(data_width=16, word_width=64, samples_per_packet=1024)
self.comb += [
    chain.source.connect(self.packetizer.sink),
    self.packetizer.source.connect(self.pcie_dma0.sink),   # LitePCIeDMA writer.
]
```

For debug-style visibility (rather than data transport), `LiteDSPCapture` + the `analysis/` blocks play
the role LiteScope plays for logic: trigger, record, inspect over the bridge.

## Software access

CSR fields are documented in the generated register map. Inside a LiteX SoC, the registers are
reachable through the usual paths: generated `csr.h` accessors for firmware, and
`litex_server`/`RemoteClient` for host-side control (UART/Ethernet/PCIe bridges).

## Installation

```bash
pip install -e .   # from the repository, or:
litex_setup --init --install   # once litedsp is registered in litex_setup repos.
```
