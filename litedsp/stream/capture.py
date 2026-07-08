#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceProcess
from litex.soc.interconnect                  import stream

from litedsp.common import iq_layout

# Trigger / Capture (scope) ------------------------------------------------------------------------

@ResetInserter()
class Capture(LiteXModule):
    """Scope-like capture: on a trigger, record ``depth`` I/Q samples to RAM, then stream them out.

    Taps the input (always ready, never backpressures the live stream). Triggers on a rising
    edge of ``I`` past ``threshold`` or on a ``force`` pulse; captures ``depth`` samples, then
    presents them on ``source`` and re-arms once read out. ``done`` is asserted while the
    captured buffer is ready/being read out; with ``with_irq=True`` its rising edge raises an
    interrupt (``ev.done``).

    Readout paths: the ``source`` stream (feed a ``CSRReader`` for CPU-less bridges), or —
    with ``with_wishbone=True`` / ``add_wishbone()`` — a read-only Wishbone window on the
    buffer (``self.bus``, one sample per 32-bit word) for fast memory-mapped drains over
    Etherbone (``soc.bus.add_slave(..., capture.bus, SoCRegion(size=capture.mem_size, ...))``).
    """
    def __init__(self, depth=1024, data_width=16, with_csr=True, with_irq=False,
        with_wishbone=False):
        assert data_width <= 16                            # I/Q packed in one 32-bit word.
        self.depth  = depth
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.threshold = Signal((data_width, True))
        self.force     = Signal()
        self.armed     = Signal()
        self.done      = Signal()

        # # #

        mem = Memory(2*data_width, depth)
        self.mem      = mem
        self.mem_size = depth*4                            # Bytes (one 32-bit word per sample).
        wp  = mem.get_port(write_capable=True)
        rp  = mem.get_port(async_read=True)
        self.specials += mem, wp, rp

        wptr = Signal(max=depth)
        rptr = Signal(max=depth)
        above = Signal()
        prev_above = Signal()
        self.comb += above.eq(self.sink.i > self.threshold)
        self.sync += If(self.sink.valid, prev_above.eq(above))

        self.comb += [
            self.sink.ready.eq(1),                                  # Non-intrusive tap.
            # Slice (not mask): `signed & mask` widens to N+1 bits and would shift Q up a bit.
            wp.adr.eq(wptr), wp.dat_w.eq(Cat(self.sink.i[:data_width], self.sink.q[:data_width])),
            rp.adr.eq(rptr),
            self.source.i.eq(rp.dat_r[:data_width]),
            self.source.q.eq(rp.dat_r[data_width:]),
        ]

        self.fsm = fsm = FSM(reset_state="ARM")
        fsm.act("ARM",
            self.armed.eq(1),
            If(self.sink.valid & (self.force | (above & ~prev_above)),
                wp.we.eq(1),                                       # Capture the triggering sample.
                NextValue(wptr, 1),
                NextState("CAPTURE"),
            )
        )
        fsm.act("CAPTURE",
            wp.we.eq(self.sink.valid),
            If(self.sink.valid,
                If(wptr == (depth - 1), NextValue(rptr, 0), NextState("READOUT"))
                .Else(NextValue(wptr, wptr + 1)),
            )
        )
        fsm.act("READOUT",
            self.done.eq(1),
            self.source.valid.eq(1),
            self.source.first.eq(rptr == 0),
            self.source.last.eq(rptr == (depth - 1)),
            If(self.source.ready,
                If(rptr == (depth - 1), NextValue(wptr, 0), NextState("ARM"))
                .Else(NextValue(rptr, rptr + 1)),
            )
        )

        if with_csr:
            self._threshold = CSRStorage(data_width, name="threshold", description="Trigger level (I).")
            self._force     = CSRStorage(1, name="force", description="Force trigger.")
            self._status    = CSRStatus(fields=[
                CSRField("armed", size=1, description="Waiting for trigger."),
                CSRField("done",  size=1, description="Capture complete, buffer ready."),
            ])
            self.comb += [
                self.threshold.eq(self._threshold.storage),
                self.force.eq(self._force.storage),
                self._status.fields.armed.eq(self.armed),
                self._status.fields.done.eq(self.done),
            ]
        if with_irq:
            self.add_irq()
        if with_wishbone:
            self.add_wishbone()

    def add_irq(self):
        self.ev      = EventManager()
        self.ev.done = EventSourceProcess(edge="rising", description="Capture complete, buffer ready.")
        self.ev.finalize()
        self.comb += self.ev.done.trigger.eq(self.done)

    def add_wishbone(self):
        from litex.soc.interconnect import wishbone
        self.wb_sram = wishbone.SRAM(self.mem, read_only=True)
        self.bus     = self.wb_sram.bus
