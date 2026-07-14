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

# Squelch ------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSquelch(LiteXModule):
    """Mute the I/Q stream when instantaneous power ``I**2 + Q**2`` is below threshold.

    Hysteresis: opens above ``open_threshold``, closes below ``close_threshold`` (set
    ``close < open``). When closed, the output is zeroed (samples still flow). ``open`` status
    reflects the gate state. With ``with_irq=True``, gate open/close edges raise interrupts
    (``ev.opened`` / ``ev.closed``).
    """
    def __init__(self, data_width=16, with_csr=True, with_irq=False):
        self.data_width  = data_width
        self.power_width = 2*data_width + 1
        self.latency     = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.open_threshold  = Signal(self.power_width, reset=0)  # Open gate at/above this power.
        self.close_threshold = Signal(self.power_width, reset=0)  # Close gate below this power.
        self.open            = Signal()                           # Gate state (1: passing).

        # # #

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        # Gate Hysteresis.
        # ----------------
        power = Signal(self.power_width)
        self.comb += power.eq(self.sink.i*self.sink.i + self.sink.q*self.sink.q)
        # Gate state updates only on accepted samples (holds during stalls).
        self.sync += If(self.sink.valid & adv,
            If(power >= self.open_threshold, self.open.eq(1)
            ).Elif(power < self.close_threshold, self.open.eq(0)),
        )

        # Output.
        # -------
        self.sync += If(adv,
            self.source.i.eq(Mux(self.open, self.sink.i, 0)),
            self.source.q.eq(Mux(self.open, self.sink.q, 0)),
            self.source.valid.eq(self.sink.valid),
        )

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev        = EventManager()
        self.ev.opened = EventSourceProcess(edge="rising",  description="Squelch gate opened.")
        self.ev.closed = EventSourceProcess(edge="falling", description="Squelch gate closed.")
        self.ev.finalize()
        # Both events watch the same gate level, on opposite edges.
        self.comb += [
            self.ev.opened.trigger.eq(self.open),
            self.ev.closed.trigger.eq(self.open),
        ]

    def add_csr(self):
        self._open  = CSRStorage(self.power_width, name="open_threshold",
            description="Open the gate at/above this power.")
        self._close = CSRStorage(self.power_width, name="close_threshold",
            description="Close the gate below this power (set < open for hysteresis).")
        self._status = CSRStatus(fields=[CSRField("open", size=1, description="Gate open.")])
        self.comb += [
            self.open_threshold.eq(self._open.storage),
            self.close_threshold.eq(self._close.storage),
            self._status.fields.open.eq(self.open),
        ]
