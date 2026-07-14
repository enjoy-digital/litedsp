#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""I/Q samples over LiteEth UDP: stream a chain's output to a host / accept samples from it.

``LiteDSPUDPIQStreamer`` sends the I/Q stream as fixed-size UDP packets (``samples_per_packet``
word-packed samples per datagram, first sample in the LSBs); ``LiteDSPUDPIQReceiver`` is the reverse
path. Both take the LiteEthUDP core (a user port is requested on its crossbar) — or directly a
``LiteEthUDPUserPort``, which keeps them simulable without the full stack:

    udp = LiteEthUDPIPCore(phy, mac_address=..., ip_address=..., clk_freq=...)
    self.iq_streamer = LiteDSPUDPIQStreamer(udp.udp, ip_address="192.168.1.100", udp_port=6000)
    self.comb += chain.source.connect(self.iq_streamer.sink)
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import iq_layout
from litedsp.frontend.packet import LiteDSPIQPacketizer, LiteDSPIQDepacketizer

# Helpers ------------------------------------------------------------------------------------------

def _get_port(udp, udp_port, word_width):
    """Return a UDP user port: from the core's crossbar, or ``udp`` itself if already a port."""
    if hasattr(udp, "crossbar"):
        return udp.crossbar.get_port(udp_port, dw=word_width)
    return udp

# UDP IQ Streamer ----------------------------------------------------------------------------------

class LiteDSPUDPIQStreamer(LiteXModule):
    """I/Q stream -> fixed-size UDP packets toward ``ip_address``:``udp_port`` (LiteEth)."""
    def __init__(self, udp, ip_address, udp_port, data_width=16, word_width=32,
        samples_per_packet=256, with_csr=True):
        self.sink = stream.Endpoint(iq_layout(data_width))

        # # #

        from liteeth.frontend.stream import LiteEthStream2UDPTX

        words_per_packet = samples_per_packet*2*data_width//word_width
        self.packetizer  = LiteDSPIQPacketizer(data_width=data_width, word_width=word_width,
            samples_per_packet=samples_per_packet, with_csr=with_csr)
        self.tx = LiteEthStream2UDPTX(ip_address=ip_address, udp_port=udp_port,
            data_width=word_width, fifo_depth=words_per_packet)
        port = _get_port(udp, udp_port, word_width)
        self.comb += [
            self.sink.connect(self.packetizer.sink),
            self.packetizer.source.connect(self.tx.sink, keep={"valid", "ready", "last", "data"}),
            self.tx.source.connect(port.sink),
            port.source.ready.eq(1),                     # TX-only port: discard RX.
        ]

# UDP IQ Receiver ----------------------------------------------------------------------------------

class LiteDSPUDPIQReceiver(LiteXModule):
    """UDP packets on ``udp_port`` -> I/Q stream (LiteEth)."""
    def __init__(self, udp, udp_port, data_width=16, word_width=32, fifo_depth=64, with_csr=True):
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        from liteeth.frontend.stream import LiteEthUDP2StreamRX

        self.rx = LiteEthUDP2StreamRX(udp_port=udp_port, data_width=word_width,
            fifo_depth=fifo_depth)
        self.depacketizer = LiteDSPIQDepacketizer(data_width=data_width, word_width=word_width,
            with_csr=with_csr)
        port = _get_port(udp, udp_port, word_width)
        self.comb += [
            port.source.connect(self.rx.sink),
            self.rx.source.connect(self.depacketizer.sink, keep={"valid", "ready", "last", "data"}),
            self.depacketizer.source.connect(self.source),
        ]
