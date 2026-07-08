#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""DMA capture/replay: bridge I/Q streams to/from system memory.

``DMACapture`` packs an I/Q stream into memory words (:class:`~litedsp.stream.adapt.IQPack`) and
writes them to a base/length memory window through a DMA writer; ``DMAReplay`` reads a window back
and unpacks it into an I/Q stream, with optional looping for continuous replay. This upgrades
capture/replay from CSR-window depth to sustained-rate, memory-sized buffers.

Two backends, selected by the constructor argument:

- ``bus=`` (Wishbone): uses :mod:`litex.soc.cores.dma`; add the bus as a DMA master to the SoC
  (``soc.bus.add_master(master=dut.bus)``). Fits DRAM-less SoCs or low sample rates.
- ``port=`` (LiteDRAM native port): uses :mod:`litedram.frontend.dma` on a crossbar port
  (``port = soc.sdram.crossbar.get_port()``), for sustained sample rates with wide words.

Control is the standard LiteX DMA register set (``base``/``length`` in bytes, ``enable``,
``done``, ``loop``, ``offset``), exposed as CSRs with ``with_csr=True`` (default) or — Wishbone
backend only — as plain control Signals with ``with_csr=False`` per the LiteDSP convention.
While disabled, ``DMACapture`` drops incoming samples (no backpressure on a free-running chain).
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common       import iq_layout
from litedsp.stream.adapt import IQPack, IQUnpack

# Helpers ------------------------------------------------------------------------------------------

def _word_ratio(word_width, data_width):
    ratio = word_width // (2*data_width)
    assert ratio >= 1 and ratio*2*data_width == word_width, \
        f"memory word width ({word_width}) must be a multiple of the I/Q sample width ({2*data_width})"
    return ratio

# DMA Capture --------------------------------------------------------------------------------------

class DMACapture(LiteXModule):
    """Capture an I/Q stream to a memory window through DMA (Wishbone ``bus=`` or LiteDRAM ``port=``)."""
    def __init__(self, data_width=16, bus=None, port=None, fifo_depth=16, with_csr=True):
        assert (bus is None) != (port is None), "provide exactly one of bus= (Wishbone) / port= (LiteDRAM)"
        self.data_width = data_width
        self.sink       = stream.Endpoint(iq_layout(data_width))

        # # #

        # DMA writer backend.
        if bus is not None:
            from litex.soc.cores.dma import WishboneDMAWriter
            self.bus    = bus
            self.writer = WishboneDMAWriter(bus, with_byteswap=False, with_csr=with_csr)
            if not with_csr:
                self.writer.add_ctrl()
            word_width  = bus.data_width
        else:
            from litedram.frontend.dma import LiteDRAMDMAWriter
            assert with_csr, "the LiteDRAM backend is CSR-controlled (with_csr=True)"
            self.port   = port
            self.writer = LiteDRAMDMAWriter(port, fifo_depth=fifo_depth, with_csr=True)
            word_width  = port.data_width

        # Control Signal aliases (Wishbone backend, with_csr=False).
        if not with_csr:
            self.base,   self.length = self.writer.base, self.writer.length
            self.enable, self.done   = self.writer.enable, self.writer.done
            self.loop,   self.offset = self.writer.loop, self.writer.offset

        # Samples -> memory words.
        self.pack = IQPack(ratio=_word_ratio(word_width, data_width), data_width=data_width)
        self.comb += [
            self.sink.connect(self.pack.sink),
            self.pack.source.connect(self.writer.sink),
        ]

# DMA Replay ---------------------------------------------------------------------------------------

class DMAReplay(LiteXModule):
    """Replay an I/Q stream from a memory window through DMA (Wishbone ``bus=`` or LiteDRAM ``port=``)."""
    def __init__(self, data_width=16, bus=None, port=None, fifo_depth=16, with_csr=True):
        assert (bus is None) != (port is None), "provide exactly one of bus= (Wishbone) / port= (LiteDRAM)"
        self.data_width = data_width
        self.source     = stream.Endpoint(iq_layout(data_width))

        # # #

        # DMA reader backend.
        if bus is not None:
            from litex.soc.cores.dma import WishboneDMAReader
            self.bus    = bus
            self.reader = WishboneDMAReader(bus, fifo_depth=fifo_depth, with_byteswap=False,
                with_csr=with_csr)
            if not with_csr:
                self.reader.add_ctrl()
            word_width  = bus.data_width
        else:
            from litedram.frontend.dma import LiteDRAMDMAReader
            assert with_csr, "the LiteDRAM backend is CSR-controlled (with_csr=True)"
            self.port   = port
            self.reader = LiteDRAMDMAReader(port, fifo_depth=fifo_depth, with_csr=True)
            word_width  = port.data_width

        # Control Signal aliases (Wishbone backend, with_csr=False).
        if not with_csr:
            self.base,   self.length = self.reader.base, self.reader.length
            self.enable, self.done   = self.reader.enable, self.reader.done
            self.loop,   self.offset = self.reader.loop, self.reader.offset

        # Memory words -> samples.
        self.unpack = IQUnpack(ratio=_word_ratio(word_width, data_width), data_width=data_width)
        self.comb += [
            self.reader.source.connect(self.unpack.sink),
            self.unpack.source.connect(self.source),
        ]
