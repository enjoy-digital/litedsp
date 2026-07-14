#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Elastic stream FIFO for decoupling rate/timing-mismatched chain stages.

Thin typed wrapper over LiteX ``stream.SyncFIFO`` that keeps the LiteDSP I/Q (or real) layout
and exposes the occupancy level (and overflow flag) over CSR. Use it to absorb bursts between a
producer and a slower/backpressuring consumer, or to give a long chain a register boundary.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

# Stream FIFO --------------------------------------------------------------------------------------

class LiteDSPStreamFIFO(LiteXModule):
    """First-word-fall-through synchronous FIFO for an I/Q (or custom-``layout``) stream."""
    def __init__(self, depth=16, data_width=16, layout=None, with_csr=True):
        assert depth >= 1
        layout      = layout if layout is not None else iq_layout(data_width)
        self.depth  = depth
        self.sink   = stream.Endpoint(layout)
        self.source = stream.Endpoint(layout)
        self.level    = Signal(max=depth + 1)   # Current occupancy.
        self.overflow = Signal()                # Sticky: a sample was dropped (sink stalled).

        # # #

        # FIFO.
        # -----
        self.fifo = fifo = stream.SyncFIFO(layout, depth)
        self.comb += [
            self.sink.connect(fifo.sink),
            fifo.source.connect(self.source),
            self.level.eq(fifo.level),
        ]

        # Overflow.
        # ---------
        # Overflow = master pushed (valid) while the FIFO could not accept (ready low).
        self.sync += If(self.sink.valid & ~self.sink.ready, self.overflow.eq(1))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._status = CSRStatus(fields=[
            CSRField("level",    size=self.level.nbits, description="Current FIFO occupancy."),
            CSRField("overflow", size=1, offset=16,     description="A sample was dropped (sticky)."),
        ])
        self.comb += [
            self._status.fields.level.eq(self.level),
            self._status.fields.overflow.eq(self.overflow),
        ]
