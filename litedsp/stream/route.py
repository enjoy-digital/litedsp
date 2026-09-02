#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, check, real_layout, tdm_layout, tdm_channel

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

# TDM Mux ------------------------------------------------------------------------------------------

class LiteDSPTDMMux(LiteXModule):
    """Interleave ``n_channels`` mono streams into one channel-tagged TDM stream (strict
    round-robin: beat ``k`` of the frame is taken from ``sinks[k]``, tagged ``channel = k``).
    Combinational (latency 0): a frame advances one beat per accepted transfer, so a slow input
    stalls the frame (the outputs of a multi-channel front-end stay time-aligned)."""
    def __init__(self, n_channels=2, data_width=24, with_csr=True):
        check(n_channels >= 1, "expected n_channels >= 1")
        self.n_channels = n_channels
        self.data_width = data_width
        self.latency    = 0
        self.sinks  = [stream.Endpoint(real_layout(data_width)) for _ in range(n_channels)]
        self.source = stream.Endpoint(tdm_layout(data_width, n_channels))

        # # #

        idx = Signal(max=max(2, n_channels))
        cases = {}
        for k, sink in enumerate(self.sinks):
            cases[k] = [
                self.source.valid.eq(sink.valid),
                self.source.data.eq(sink.data),
                self.source.first.eq(sink.first),
                self.source.last.eq(sink.last),
                sink.ready.eq(self.source.ready),
            ]
        self.comb += Case(idx, cases)
        if n_channels > 1:
            self.comb += self.source.channel.eq(idx)
            self.sync += If(self.source.valid & self.source.ready,
                idx.eq(Mux(idx == n_channels - 1, 0, idx + 1)),
            )

# TDM Demux ----------------------------------------------------------------------------------------

class LiteDSPTDMDemux(LiteXModule):
    """Split a channel-tagged TDM stream into ``n_channels`` mono streams: every beat is routed
    to ``sources[channel]`` (combinational, latency 0; a stalled output stalls the stream)."""
    def __init__(self, n_channels=2, data_width=24, with_csr=True):
        check(n_channels >= 1, "expected n_channels >= 1")
        self.n_channels = n_channels
        self.data_width = data_width
        self.latency    = 0
        self.sink    = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.sources = [stream.Endpoint(real_layout(data_width)) for _ in range(n_channels)]

        # # #

        cases = {}
        for k, source in enumerate(self.sources):
            cases[k] = [
                source.valid.eq(self.sink.valid),
                source.data.eq(self.sink.data),
                source.first.eq(self.sink.first),
                source.last.eq(self.sink.last),
                self.sink.ready.eq(source.ready),
            ]
        self.comb += Case(tdm_channel(self.sink), cases)
