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
    """Route one of ``n`` sinks to a single source, selected by ``sel`` (runtime).

    Parameters
    ----------
    n : int
        Number of selectable input channels (sinks). Sizes the ``sel`` signal/CSR; unselected
        sinks are backpressured (ready held low), not drained.
    layout : list
        Payload layout (default ``iq_layout(data_width)``); any layout works (real, TDM, abc).
    """
    def __init__(self, n=2, data_width=16, with_csr=True, layout=None):
        if layout is None:
            layout = iq_layout(data_width)
        self.n      = n
        self.latency = 0
        self.sinks  = [stream.Endpoint(layout) for _ in range(n)]
        self.source = stream.Endpoint(layout)
        self.sel    = Signal(max=max(2, n))  # Selected input channel (runtime).

        # # #

        # Mux.
        # ----
        cases = {k: self.sinks[k].connect(self.source) for k in range(n)}
        self.comb += Case(self.sel, cases)   # Unselected sinks: ready stays 0.

        # CSR.
        # ----
        if with_csr:
            self._sel = CSRStorage(self.sel.nbits, name="sel", description="Selected input channel.")
            self.comb += self.sel.eq(self._sel.storage)

class LiteDSPChannelDemux(LiteXModule):
    """Route a single sink to one of ``n`` sources, selected by ``sel`` (runtime).

    Parameters
    ----------
    n : int
        Number of selectable output channels (sources). Sizes the ``sel`` signal/CSR;
        unselected sources see valid held low (no data is duplicated to them).
    layout : list
        Payload layout (default ``iq_layout(data_width)``); any layout works (real, TDM, abc).
    """
    def __init__(self, n=2, data_width=16, with_csr=True, layout=None):
        if layout is None:
            layout = iq_layout(data_width)
        self.n       = n
        self.latency = 0
        self.sink    = stream.Endpoint(layout)
        self.sources = [stream.Endpoint(layout) for _ in range(n)]
        self.sel     = Signal(max=max(2, n))  # Selected output channel (runtime).

        # # #

        # Demux.
        # ------
        cases = {k: self.sink.connect(self.sources[k]) for k in range(n)}
        self.comb += Case(self.sel, cases)   # Unselected sources: valid stays 0.

        # CSR.
        # ----
        if with_csr:
            self._sel = CSRStorage(self.sel.nbits, name="sel", description="Selected output channel.")
            self.comb += self.sel.eq(self._sel.storage)
