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
    """I/Q stream -> fixed-size UDP packets toward ``ip_address``:``udp_port`` (LiteEth).

    With ``with_timestamp=True`` each datagram starts with the packetizer's 128-bit timestamp
    header (see :mod:`litedsp.frontend.packet`); connect a
    :class:`~litedsp.stream.timestamp.LiteDSPTimeCore` count to the exposed ``time`` Signal.
    """
    def __init__(self, udp, ip_address, udp_port, data_width=16, word_width=32,
        samples_per_packet=256, with_timestamp=False, stream_id=0, with_csr=True):
        self.sink = stream.Endpoint(iq_layout(data_width))

        # # #

        from liteeth.frontend.stream import LiteEthStream2UDPTX

        # Submodules.
        # -----------
        words_per_packet = samples_per_packet*2*data_width//word_width  # Words per datagram.
        if with_timestamp:
            words_per_packet += 128//word_width                         # + timestamp header.
        self.packetizer  = LiteDSPIQPacketizer(data_width=data_width, word_width=word_width,
            samples_per_packet=samples_per_packet, with_timestamp=with_timestamp,
            stream_id=stream_id, with_csr=with_csr)
        if with_timestamp:
            self.time = self.packetizer.time  # Connect LiteDSPTimeCore.count.
        self.tx = LiteEthStream2UDPTX(ip_address=ip_address, udp_port=udp_port,
            data_width=word_width, fifo_depth=words_per_packet)  # FIFO buffers one full packet.

        # Datapath.
        # ---------
        port = _get_port(udp, udp_port, word_width)
        self.comb += [
            self.sink.connect(self.packetizer.sink),
            self.packetizer.source.connect(self.tx.sink, keep={"valid", "ready", "last", "data"}),
            self.tx.source.connect(port.sink),
            port.source.ready.eq(1),                     # TX-only port: discard RX.
        ]

# UDP IQ Receiver ----------------------------------------------------------------------------------

class LiteDSPUDPIQReceiver(LiteXModule):
    """UDP packets on ``udp_port`` -> I/Q stream (LiteEth).

    With ``with_timestamp=True`` the depacketizer consumes the 128-bit timestamp header of
    each datagram and the ``source`` carries the recovered ``timestamp``/``stream_id`` params
    (strip with :class:`~litedsp.stream.timestamp.LiteDSPTimeUntagger` before a plain chain).
    """
    def __init__(self, udp, udp_port, data_width=16, word_width=32, fifo_depth=64,
        with_timestamp=False, with_csr=True):

        # # #

        from liteeth.frontend.stream import LiteEthUDP2StreamRX

        # Submodules.
        # -----------
        self.rx = LiteEthUDP2StreamRX(udp_port=udp_port, data_width=word_width,
            fifo_depth=fifo_depth)
        self.depacketizer = LiteDSPIQDepacketizer(data_width=data_width, word_width=word_width,
            with_timestamp=with_timestamp, with_csr=with_csr)
        self.source = stream.Endpoint(self.depacketizer.source.description)

        # Datapath.
        # ---------
        port = _get_port(udp, udp_port, word_width)
        self.comb += [
            port.source.connect(self.rx.sink),
            self.rx.source.connect(self.depacketizer.sink, keep={"valid", "ready", "last", "data"}),
            self.depacketizer.source.connect(self.source),
        ]
