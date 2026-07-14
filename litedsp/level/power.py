#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

# Power --------------------------------------------------------------------------------------------

class LiteDSPPower(LiteXModule):
    """Average power meter: passes the I/Q stream through and measures mean ``I**2 + Q**2``.

    The instantaneous power is accumulated over ``2**window_log2`` accepted samples, then the
    block average (accumulator >> window_log2) is latched into ``power`` and ``update`` pulses.
    Unlike the original tetra ``LiteDSPPower``, the averaging window is actually implemented.
    """
    def __init__(self, data_width=16, max_window_log2=20, with_csr=True):
        self.data_width      = data_width
        self.max_window_log2 = max_window_log2
        self.power_width     = 2*data_width
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.window_log2 = Signal(max=max_window_log2 + 1)        # Averaging window = 2**window_log2.
        self.power       = Signal(self.power_width)               # Latched average power.
        self.update      = Signal()                              # Pulses when `power` updates.

        # # #

        # Passthrough (measurement only, zero added latency).
        # ---------------------------------------------------
        self.comb += self.sink.connect(self.source)

        sample = Signal()
        self.comb += sample.eq(self.sink.valid & self.sink.ready)

        # Instantaneous power I**2 + Q**2.
        # --------------------------------
        inst = Signal(2*data_width + 1)
        self.comb += inst.eq(self.sink.i*self.sink.i + self.sink.q*self.sink.q)

        # Accumulate over the window then latch the average.
        # --------------------------------------------------
        acc   = Signal(2*data_width + max_window_log2)
        count = Signal(max_window_log2 + 1)
        last  = Signal()
        self.comb += last.eq(count == ((1 << self.window_log2) - 1))
        self.sync += [
            self.update.eq(0),
            If(sample,
                If(last,
                    self.power.eq((acc + inst) >> self.window_log2),
                    self.update.eq(1),
                    acc.eq(0),
                    count.eq(0),
                ).Else(
                    acc.eq(acc + inst),
                    count.eq(count + 1),
                )
            )
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._window = CSRStorage(self.window_log2.nbits, reset=0, name="window",
            description="Averaging window as a power of two (window = 2**window_log2).")
        self._power  = CSRStatus(self.power_width, name="power",
            description="Latest block-averaged power (I**2 + Q**2).")
        self.comb += [
            self.window_log2.eq(self._window.storage),
            self._power.status.eq(self.power),
        ]
