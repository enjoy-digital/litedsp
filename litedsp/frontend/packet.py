#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""I/Q streams <-> framed wide-word streams: the generic glue toward host links.

``LiteDSPIQPacketizer`` frames the sample stream every ``samples_per_packet`` samples
(:class:`~litedsp.stream.framing.LiteDSPStreamFramer`) and packs samples into ``word_width``-bit words
(:class:`~litedsp.stream.adapt.LiteDSPIQPack`, first sample in the LSBs): the resulting
``data``+``last`` stream maps directly onto UDP payloads (LiteEth), host DMA word streams
(LitePCIe ``dma.sink``), or any AXI-Stream-with-tlast consumer. ``LiteDSPIQDepacketizer`` is the exact
inverse for the host -> FPGA direction.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common         import iq_layout
from litedsp.stream.adapt   import LiteDSPIQPack, LiteDSPIQUnpack
from litedsp.stream.framing import LiteDSPStreamFramer, LiteDSPStreamDeframer

# IQ Packetizer ------------------------------------------------------------------------------------

class LiteDSPIQPacketizer(LiteXModule):
    """I/Q stream -> ``word_width``-bit word stream with ``last`` every ``samples_per_packet``."""
    def __init__(self, data_width=16, word_width=32, samples_per_packet=256, with_csr=True):
        ratio = word_width // (2*data_width)  # I/Q samples per word.
        assert ratio >= 1 and ratio*2*data_width == word_width
        assert samples_per_packet % ratio == 0
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint([("data", word_width)])

        # # #

        self.framer = LiteDSPStreamFramer(length=samples_per_packet, data_width=data_width,
            with_csr=with_csr)
        self.pack   = LiteDSPIQPack(ratio=ratio, data_width=data_width)
        self.comb += [
            self.sink.connect(self.framer.sink),
            self.framer.source.connect(self.pack.sink),
            self.pack.source.connect(self.source),
        ]

# IQ Depacketizer ----------------------------------------------------------------------------------

class LiteDSPIQDepacketizer(LiteXModule):
    """``word_width``-bit word stream -> I/Q stream (inverse of :class:`LiteDSPIQPacketizer`)."""
    def __init__(self, data_width=16, word_width=32, with_csr=True):
        ratio = word_width // (2*data_width)  # I/Q samples per word.
        assert ratio >= 1 and ratio*2*data_width == word_width
        self.sink   = stream.Endpoint([("data", word_width)])
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.unpack   = LiteDSPIQUnpack(ratio=ratio, data_width=data_width)
        self.deframer = LiteDSPStreamDeframer(data_width=data_width, with_csr=with_csr)
        self.comb += [
            self.sink.connect(self.unpack.sink),
            self.unpack.source.connect(self.deframer.sink),
            self.deframer.source.connect(self.source),
        ]
