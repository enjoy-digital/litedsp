#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Clock-domain crossing and width adaptation for I/Q streams (thin wrappers over LiteX).

``IQPack`` / ``IQUnpack`` bridge the per-sample I/Q layout to a wide flat bus word (e.g. four
16-bit I/Q samples in one 128-bit AXI-Stream ``tdata``), which is how a DSP chain meets a wide
DMA/AXI interface. They are exact inverses, so ``IQUnpack(IQPack(x)) == x``.

``IQSerialToParallel`` / ``IQParallelToSerial`` bridge the per-sample layout to the multi-
sample-per-cycle layout (``iq_layout(data_width, n_samples)``) used by the parallel datapath
blocks, gathering/spreading ``n_samples`` consecutive samples per beat (lane 0 = first sample).
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import iq_layout, iq_lanes

# Clock-Domain Crossing ----------------------------------------------------------------------------

class IQClockDomainCrossing(LiteXModule):
    """Cross an I/Q stream between clock domains via a LiteX async FIFO."""
    def __init__(self, cd_from="sys", cd_to="sys", data_width=16, depth=8):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.cdc = stream.ClockDomainCrossing(iq_layout(data_width),
            cd_from=cd_from, cd_to=cd_to, depth=depth)
        self.comb += [
            self.sink.connect(self.cdc.sink),
            self.cdc.source.connect(self.source),
        ]

# Sample Packing / Unpacking -----------------------------------------------------------------------

class IQPack(LiteXModule):
    """Pack ``ratio`` consecutive I/Q samples into one wide ``data`` word (LSB = first sample)."""
    def __init__(self, ratio=4, data_width=16):
        assert ratio >= 1
        sw          = 2*data_width
        self.ratio  = ratio
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint([("data", sw*ratio)])

        # # #

        self.conv = conv = stream.Converter(sw, sw*ratio)
        self.comb += [
            conv.sink.valid.eq(self.sink.valid),
            self.sink.ready.eq(conv.sink.ready),
            conv.sink.first.eq(self.sink.first),
            conv.sink.last.eq(self.sink.last),
            conv.sink.data.eq(Cat(self.sink.i, self.sink.q)),
            conv.source.connect(self.source),
        ]

class IQUnpack(LiteXModule):
    """Unpack one wide ``data`` word into ``ratio`` I/Q samples (inverse of :class:`IQPack`)."""
    def __init__(self, ratio=4, data_width=16):
        assert ratio >= 1
        sw          = 2*data_width
        self.ratio  = ratio
        self.sink   = stream.Endpoint([("data", sw*ratio)])
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.conv = conv = stream.Converter(sw*ratio, sw)
        self.comb += [
            self.sink.connect(conv.sink),
            self.source.valid.eq(conv.source.valid),
            conv.source.ready.eq(self.source.ready),
            self.source.first.eq(conv.source.first),
            self.source.last.eq(conv.source.last),
            self.source.i.eq(conv.source.data[:data_width]),
            self.source.q.eq(conv.source.data[data_width:]),
        ]

# Serial <-> Parallel (multi-sample-per-cycle) -------------------------------------------------------

class IQSerialToParallel(LiteXModule):
    """Gather ``n_samples`` consecutive I/Q samples into one multi-sample beat (lane 0 first)."""
    def __init__(self, n_samples=2, data_width=16):
        assert n_samples >= 1
        sw          = 2*data_width
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width, n_samples))

        # # #

        self.conv = conv = stream.Converter(sw, sw*n_samples)
        self.comb += [
            conv.sink.valid.eq(self.sink.valid),
            self.sink.ready.eq(conv.sink.ready),
            conv.sink.first.eq(self.sink.first),
            conv.sink.last.eq(self.sink.last),
            conv.sink.data.eq(Cat(self.sink.i, self.sink.q)),
            self.source.valid.eq(conv.source.valid),
            conv.source.ready.eq(self.source.ready),
            self.source.first.eq(conv.source.first),
            self.source.last.eq(conv.source.last),
        ]
        for k, (i, q) in enumerate(iq_lanes(self.source, data_width, n_samples)):
            self.comb += [
                i.eq(conv.source.data[k*sw:k*sw + data_width]),
                q.eq(conv.source.data[k*sw + data_width:(k + 1)*sw]),
            ]

class IQParallelToSerial(LiteXModule):
    """Spread one multi-sample beat back into ``n_samples`` consecutive I/Q samples."""
    def __init__(self, n_samples=2, data_width=16):
        assert n_samples >= 1
        sw          = 2*data_width
        self.sink   = stream.Endpoint(iq_layout(data_width, n_samples))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.conv = conv = stream.Converter(sw*n_samples, sw)
        word = Signal(sw*n_samples)
        for k, (i, q) in enumerate(iq_lanes(self.sink, data_width, n_samples)):
            self.comb += word[k*sw:(k + 1)*sw].eq(Cat(i, q))
        self.comb += [
            conv.sink.valid.eq(self.sink.valid),
            self.sink.ready.eq(conv.sink.ready),
            conv.sink.first.eq(self.sink.first),
            conv.sink.last.eq(self.sink.last),
            conv.sink.data.eq(word),
            self.source.valid.eq(conv.source.valid),
            conv.source.ready.eq(self.source.ready),
            self.source.first.eq(conv.source.first),
            self.source.last.eq(conv.source.last),
            self.source.i.eq(conv.source.data[:data_width]),
            self.source.q.eq(conv.source.data[data_width:]),
        ]
