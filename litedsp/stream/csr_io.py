#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Bus-driven stream endpoints: inject/observe a chain from the CSR / AXI-Lite side.

These let firmware drive a processing chain and read it back without external data ports —
useful for bring-up, self-test, and control-plane sample injection. ``CSRSource`` pushes one
sample per CSR write; ``CSRSink`` exposes the last sample plus a transfer counter; ``NullSink``
is an always-ready drain with a counter (terminate a branch / measure throughput).
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

# CSR Source ---------------------------------------------------------------------------------------

class CSRSource(LiteXModule):
    """Emit one I/Q sample per ``push`` strobe, with the payload set from CSR registers."""
    def __init__(self, data_width=16, with_csr=True):
        self.data_width = data_width
        self.source = stream.Endpoint(iq_layout(data_width))
        self.i    = Signal((data_width, True))
        self.q    = Signal((data_width, True))
        self.push = Signal()                    # 1-cycle strobe: latch (i,q) and present it.

        # # #

        self.sync += [
            If(self.push,
                self.source.valid.eq(1),
                self.source.i.eq(self.i),
                self.source.q.eq(self.q),
            ).Elif(self.source.ready,
                self.source.valid.eq(0),
            )
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._sample = CSRStorage(fields=[
            CSRField("i", size=self.data_width, description="Sample I (signed)."),
            CSRField("q", size=self.data_width, offset=16, description="Sample Q (signed)."),
        ])
        self._push = CSRStorage(1, name="push", description="Strobe: emit the sample (write to push).")
        self.comb += [
            self.i.eq(self._sample.fields.i),
            self.q.eq(self._sample.fields.q),
            self.push.eq(self._push.re),         # .re strobes for one cycle on each write.
        ]

# CSR Sink -----------------------------------------------------------------------------------------

class CSRSink(LiteXModule):
    """Always-ready sink that latches the last I/Q sample and counts transfers (CSR-readable)."""
    def __init__(self, data_width=16, with_csr=True):
        self.data_width = data_width
        self.sink  = stream.Endpoint(iq_layout(data_width))
        self.last_i = Signal((data_width, True))
        self.last_q = Signal((data_width, True))
        self.count  = Signal(32)
        self.clear  = Signal()

        # # #

        self.comb += self.sink.ready.eq(1)
        self.sync += [
            If(self.clear, self.count.eq(0)),
            If(self.sink.valid,
                self.last_i.eq(self.sink.i),
                self.last_q.eq(self.sink.q),
                If(~self.clear, self.count.eq(self.count + 1)),
            )
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._last = CSRStatus(fields=[
            CSRField("i", size=self.data_width, description="Last sample I."),
            CSRField("q", size=self.data_width, offset=16, description="Last sample Q."),
        ])
        self._count = CSRStatus(32, name="count", description="Transfers since clear.")
        self._clear = CSRStorage(1, name="clear", description="Clear the transfer counter (write to clear).")
        self.comb += [
            self._last.fields.i.eq(self.last_i),
            self._last.fields.q.eq(self.last_q),
            self._count.status.eq(self.count),
            self.clear.eq(self._clear.re),
        ]

# Null Sink ----------------------------------------------------------------------------------------

class NullSink(LiteXModule):
    """Always-ready drain that counts consumed samples (CSR-readable). Terminates a branch."""
    def __init__(self, data_width=16, with_csr=True):
        self.sink  = stream.Endpoint(iq_layout(data_width))
        self.count = Signal(32)
        self.clear = Signal()

        # # #

        self.comb += self.sink.ready.eq(1)
        self.sync += [
            If(self.clear, self.count.eq(0)),
            If(self.sink.valid & ~self.clear, self.count.eq(self.count + 1)),
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._count = CSRStatus(32, name="count", description="Samples consumed since clear.")
        self._clear = CSRStorage(1, name="clear", description="Clear the counter (write to clear).")
        self.comb += [
            self._count.status.eq(self.count),
            self.clear.eq(self._clear.re),
        ]
