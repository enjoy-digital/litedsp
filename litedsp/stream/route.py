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

# Channel Mux / Demux ------------------------------------------------------------------------------

class LiteDSPChannelMux(LiteXModule):
    """Route one of ``n`` I/Q sinks to a single source, selected by ``sel`` (runtime).

    Parameters
    ----------
    n : int
        Number of selectable input channels (sinks). Sizes the ``sel`` signal/CSR; unselected
        sinks are backpressured (ready held low), not drained.
    """
    def __init__(self, n=2, data_width=16, with_csr=True):
        self.n      = n
        self.latency = 0
        self.sinks  = [stream.Endpoint(iq_layout(data_width)) for _ in range(n)]
        self.source = stream.Endpoint(iq_layout(data_width))
        self.sel    = Signal(max=max(2, n))  # Selected input channel (runtime).

        # # #

        # Mux.
        # ----
        cases = {}
        for k in range(n):
            cases[k] = [
                self.source.valid.eq(self.sinks[k].valid),
                self.source.first.eq(self.sinks[k].first),
                self.source.last.eq(self.sinks[k].last),
                self.source.i.eq(self.sinks[k].i),
                self.source.q.eq(self.sinks[k].q),
                self.sinks[k].ready.eq(self.source.ready),
            ]
        self.comb += Case(self.sel, cases)   # Unselected sinks: ready stays 0.

        # CSR.
        # ----
        if with_csr:
            self._sel = CSRStorage(self.sel.nbits, name="sel", description="Selected input channel.")
            self.comb += self.sel.eq(self._sel.storage)

class LiteDSPChannelDemux(LiteXModule):
    """Route a single I/Q sink to one of ``n`` sources, selected by ``sel`` (runtime).

    Parameters
    ----------
    n : int
        Number of selectable output channels (sources). Sizes the ``sel`` signal/CSR;
        unselected sources see valid held low (no data is duplicated to them).
    """
    def __init__(self, n=2, data_width=16, with_csr=True):
        self.n       = n
        self.latency = 0
        self.sink    = stream.Endpoint(iq_layout(data_width))
        self.sources = [stream.Endpoint(iq_layout(data_width)) for _ in range(n)]
        self.sel     = Signal(max=max(2, n))  # Selected output channel (runtime).

        # # #

        # Demux.
        # ------
        cases = {}
        for k in range(n):
            cases[k] = [
                self.sources[k].valid.eq(self.sink.valid),
                self.sources[k].first.eq(self.sink.first),
                self.sources[k].last.eq(self.sink.last),
                self.sources[k].i.eq(self.sink.i),
                self.sources[k].q.eq(self.sink.q),
                self.sink.ready.eq(self.sources[k].ready),
            ]
        self.comb += Case(self.sel, cases)   # Unselected sources: valid stays 0.

        # CSR.
        # ----
        if with_csr:
            self._sel = CSRStorage(self.sel.nbits, name="sel", description="Selected output channel.")
            self.comb += self.sel.eq(self._sel.storage)
