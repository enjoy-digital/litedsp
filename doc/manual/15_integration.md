# Integration {#integration}

This chapter puts LiteDSP in a design. It covers the three levels of integration, from a block
in a LiteX SoC to a standalone Verilog core in a vendor flow, then the converters and links that
bring samples in and out, the clock domains, and software access to the registers.

## Three levels {#int-levels}

LiteDSP blocks are plain LiteX modules with stream endpoints, so they integrate in a LiteX SoC
like any LiteX core: instantiate them, connect their streams, and LiteX collects their registers.
The table below compares the three levels.

| Level | Unit | Control | Use when |
|-------------------|----------------------------|----------------|--------------------------------|
| Blocks in a SoC | `LiteDSP*` classes | SoC registers | The design is a LiteX SoC |
| Netlist in a SoC | `LiteDSPFlowChain` | SoC registers | The chain is drawn or scripted |
| Standalone core | `litedsp_gen` output | AXI-Lite | The design is not a LiteX SoC |

## Blocks in a LiteX SoC {#int-blocks}

Add a block, or a composite such as `LiteDSPDDC`, as a submodule of the SoC. With
`with_csr=True`, the default, its registers appear in the register map of the SoC under the
attribute name. Firmware reaches them through `csr.h`, a host through `litex_server`.

```python
from litedsp.mixing.ddc import LiteDSPDDC

class MySoC(SoCCore):
    def __init__(self, platform, **kwargs):
        SoCCore.__init__(self, platform, **kwargs)

        # DDC: NCO tuning, complex down-mix and decimation by 8, controlled by registers.
        self.ddc = LiteDSPDDC(data_width=16, decimation=8)
        self.comb += [
            adc.source.connect(self.ddc.sink),   # Any iq_layout stream source.
            self.ddc.source.connect(dma.sink),   # Any iq_layout stream sink.
        ]
```

Here the DDC registers are `ddc_nco_phase_inc`, the tuning word of its oscillator, and the
configuration status of its decimator; [Register reference](#reg-mixing) lists them. The DDC
shifts the band at the NCO frequency down to baseband: set the tuning word to the frequency to
receive, in phase units. The docstring of `LiteDSPDDC` says the opposite; the gateware follows
this manual; the fix is pending (PR #13, [Known issues](#intro-known-issues)).

Three conventions hold for every block; [the block contract](#architecture) gives the details:

- streams are LiteX `stream.Endpoint`s named `sink` and `source`, with full `valid` and `ready`
  backpressure, connected with `connect()`;
- with `with_csr=False`, the block has no registers and the parent drives its control signals
  directly, as composites do with their sub-blocks and as a design does to hard-wire a setting;
- most blocks are wrapped by `ResetInserter`: driving `block.reset` resets one block
  synchronously; composites such as the DDC, and the stream utilities, have no `reset`
  ([Reset and interrupts](#arch-reset-irq)).

## Netlists in a LiteX SoC {#int-flow}

A chain described as a flow netlist, written by hand or drawn in the editor, goes into a SoC
through `LiteDSPFlowChain`. Each block gets its registers under its netlist id as prefix, so
block `lo` of the netlist exposes `chain_lo_phase_inc` in a SoC where the chain is `self.chain`.

```python
from litedsp.flow.builder import LiteDSPFlowChain
from litedsp.flow import netlist

class MySoC(SoCCore):
    def __init__(self, platform, **kwargs):
        SoCCore.__init__(self, platform, **kwargs)
        self.chain = LiteDSPFlowChain(netlist.load("rx_chain.json"), with_csr=True)
        self.comb += [
            adc.source.connect(self.chain.endpoint("rx_in")),
            self.chain.endpoint("bb_out").connect(dma.sink),
        ]
```

The top-level ports of the netlist are endpoints, found by id with `chain.endpoint()`
([Chain builder](#tool-builder) gives the aliases and the splits and delays the builder
inserts).

## Standalone core {#int-standalone}

For a design that does not use LiteX, `litedsp_gen` generates a self-contained Verilog core
from a YAML file, with AXI-Stream data ports, an AXI-Lite control port and the register map files
`csr.csv`, `csr.json` and `csr.h`; `--vivado-ip` packages it for IP Integrator.
[Standalone core](#tool-ipcore) describes its ports, clock, reset and files.

```sh
litedsp_gen examples/ddc_core.yml --output-dir build
```

Software writes the registers at the addresses of `csr.csv`. These addresses include the
`csr_base` of the YAML file. The core decodes the low `axil_address_width` bits, so `csr_base` must
be a multiple of `2**axil_address_width`, the window the core occupies; the generator raises a
`ValueError` otherwise. Map the core at `csr_base`.

## Getting samples in and out {#int-io}

The chain only sees I/Q streams in Q1.15 by default. The boundary adapters of `litedsp/frontend/`
and the memory blocks of `litedsp/stream/` connect them to converters, memory and links.  The
table below lists them.

| Boundary | Blocks | Link |
|---------------------|----------------------------------------------------|---------------------|
| ADC, DAC | `LiteDSPADCInterface`, `LiteDSPDACInterface` | Converter pins |
| 1-bit modulators | `LiteDSPBitstreamInterface` | Sigma-delta, PDM |
| Memory | `LiteDSPDMACapture`, `LiteDSPDMAReplay` | Wishbone, LiteDRAM |
| Ethernet | `LiteDSPUDPIQStreamer`, `LiteDSPUDPIQReceiver` | LiteEth UDP |
| PCIe or any DMA | `LiteDSPIQPacketizer`, `LiteDSPIQDepacketizer` | Framed word stream |
| Debug | `LiteDSPCapture`, `LiteDSPCSRReader` | Registers, bus window |

The converter adapters align a raw converter word to a full-scale signed sample. The DMA blocks
move a stream to or from memory, with the LiteX DMA registers `base`, `length`, `enable`,
`done`, `loop` and `offset`. The packetizer cuts the stream into packets ended by `last`, for a
LitePCIe DMA or any framed sink, and the UDP streamer sends it to a host through LiteEth.
[Stream utilities and host links](#stream-frontend) describes each block; the [streaming
bench](#brd-stream) uses the UDP streamer.

For visibility rather than transport, `LiteDSPCapture` and the analysis blocks play the role
LiteScope plays for logic: trigger, record, inspect over the bridge ([Debugging](#debugging)).

## Clocks and clock domains {#int-clocks}

A LiteDSP block has no clock of its own: it runs in the domain of the module that instantiates
it, `sys` by default. Its sample rate is set by its input stream, not by its clock: a block
handles at most one beat per clock, and fewer when `valid` is low.

A parallel variant handles `n_samples` samples per beat for sample rates above the clock rate
([the block contract](#architecture)).

A converter usually has its own clock. Capture its words in that domain, then cross into the
DSP domain with `LiteDSPIQClockDomainCrossing`, an asynchronous FIFO of `depth` samples between
the domains named by `cd_from` and `cd_to`. The DSP domain must accept the converter rate on
average, or the FIFO fills and the samples the converter presents meanwhile are lost.

```python
self.adc_if = ClockDomainsRenamer("adc")(LiteDSPADCInterface(adc_width=12, data_width=16))
self.cdc    = LiteDSPIQClockDomainCrossing(cd_from="adc", cd_to="sys", data_width=16, depth=16)
self.comb  += [
    self.adc_if.source.connect(self.cdc.sink),
    self.cdc.source.connect(self.ddc.sink),
]
```

A whole chain can run in another domain through `ClockDomainsRenamer`, as any LiteX module.
Its registers, however, are written by the CSR bus in the `sys` domain, and a block moved to
another domain reads them without synchronization. The safe default is to keep the chain in the
`sys` domain and cross the streams at its edges.

The clock frequency a chain reaches depends on the blocks and their architecture options.
[Performance](#performance) gives the recorded results per block, out of context, and the
pipelined options of the filters, FFT, AGC and decoders trade latency for frequency.

## Software access {#int-software}

Inside a LiteX SoC, the registers are reached through the usual paths: the `csr.h` accessors of
the build for firmware, and `litex_server` with a `RemoteClient` for a host, over a UART,
Ethernet or PCIe bridge. The register names are the block names, or netlist ids, followed by the
register names of [Register reference](#registers).

On the host, the LiteDSP drivers add unit conversions over the raw registers: an NCO tuned in Hz,
FIR coefficients reloaded from a design, captures drained into NumPy ([Host
software](#tool-host)). The example below tunes the DDC of the first section and reads back its
frequency.

```python
from litex import RemoteClient
from litedsp.software.drivers import NCODriver

bus = RemoteClient(csr_csv="csr.csv")
bus.open()
clk_freq = bus.constants.config_clock_frequency
lo = NCODriver(bus, "ddc_nco", clk_freq=clk_freq)
lo.set_frequency(1e6)               # Receive the band at +1 MHz.
print(lo.get_frequency())
bus.close()
```

The NCO driver converts a frequency to the phase increment word `freq/clk_freq * 2**32`,
modulo 2^32, so a negative frequency, a band below the centre, is a large unsigned word. The NCO phase advances once per
accepted sample, so this conversion holds when the NCO output is accepted on every clock, as in
the benches.

Where to go next: [Benches](#boards) builds complete SoCs, [Debugging](#debugging) inspects a
running chain, [Build options](#build-options) lists the parameters of every block.
