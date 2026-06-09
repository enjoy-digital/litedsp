#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Packetize/depacketize an I/Q stream by marking frame boundaries.

``StreamFramer`` injects ``first``/``last`` every ``length`` samples (CSR-settable), which an
AXI-Stream wrapper maps directly to ``tlast`` so a DMA sees fixed-size packets. ``StreamDeframer``
is the pass-through counterpart that counts completed frames (read over CSR) and re-derives a
``first`` from incoming ``last`` — useful when consuming externally-framed data.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

# Framer -------------------------------------------------------------------------------------------

class StreamFramer(LiteXModule):
    """Pass I/Q through, asserting ``first`` at sample 0 and ``last`` at sample ``length-1``."""
    def __init__(self, length=256, data_width=16, max_length=65536, with_csr=True):
        self.length = Signal(max=max_length, reset=length)
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.latency = 0

        # # #

        cnt  = Signal(max=max_length)
        xfer = Signal()
        self.comb += [
            self.source.valid.eq(self.sink.valid),
            self.sink.ready.eq(self.source.ready),
            self.source.i.eq(self.sink.i),
            self.source.q.eq(self.sink.q),
            self.source.first.eq(cnt == 0),
            self.source.last.eq(cnt == (self.length - 1)),
            xfer.eq(self.source.valid & self.source.ready),
        ]
        self.sync += If(xfer,
            If(cnt == (self.length - 1), cnt.eq(0)).Else(cnt.eq(cnt + 1)),
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._length = CSRStorage(self.length.nbits, reset=self.length.reset.value, name="length",
            description="Frame length in samples (assert last every N).")
        self.comb += self.length.eq(self._length.storage)

# Deframer -----------------------------------------------------------------------------------------

class StreamDeframer(LiteXModule):
    """Pass I/Q through, counting frames (on ``last``) and re-deriving ``first`` after each frame."""
    def __init__(self, data_width=16, with_csr=True):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.frames = Signal(32)
        self.clear  = Signal()
        self.latency = 0

        # # #

        in_frame = Signal()                       # 0 -> next sample starts a frame.
        xfer     = Signal()
        self.comb += [
            self.source.valid.eq(self.sink.valid),
            self.sink.ready.eq(self.source.ready),
            self.source.i.eq(self.sink.i),
            self.source.q.eq(self.sink.q),
            self.source.first.eq(~in_frame),
            self.source.last.eq(self.sink.last),
            xfer.eq(self.source.valid & self.source.ready),
        ]
        self.sync += [
            If(self.clear, self.frames.eq(0)),
            If(xfer,
                in_frame.eq(~self.sink.last),
                If(self.sink.last & ~self.clear, self.frames.eq(self.frames + 1)),
            )
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._frames = CSRStatus(32, name="frames", description="Completed frames since clear.")
        self._clear  = CSRStorage(1, name="clear", description="Reset the frame counter (write to clear).")
        self.comb += [
            self._frames.status.eq(self.frames),
            self.clear.eq(self._clear.re),
        ]
