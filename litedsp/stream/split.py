#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import check, iq_layout

# Split / Duplicate --------------------------------------------------------------------------------

class LiteDSPSplit(LiteXModule):
    """Fan-out one stream to ``n`` identical sources (every source sees every sample).

    Parameters
    ----------
    n : int
        Number of duplicated output streams (>= 1). Each source sees exactly the same
        transfers, and the sink sample is consumed once every source has taken it, so the
        slowest branch paces the whole stream. A source's ``valid`` does not depend on any
        ``ready``: a branch that takes the sample early is masked (``valid`` low) until the
        other branches have taken it too, so consumers that wait for ``valid`` before raising
        ``ready`` (AXI-legal) or that join the branches again (e.g. both inputs of
        :class:`~litedsp.mixing.mixer.LiteDSPMixer`) cannot deadlock. With every source ready
        the sample passes in the same cycle (no latency, one sample per clock).
    layout : list
        Payload layout (default ``iq_layout(data_width)``); any layout works (real, TDM, abc).
    """
    def __init__(self, n=2, data_width=16, layout=None):
        check(n >= 1, "expected n >= 1")
        if layout is None:
            layout = iq_layout(data_width)
        self.n      = n
        self.latency = 0
        self.sink    = stream.Endpoint(layout)
        self.sources = [stream.Endpoint(layout) for _ in range(n)]

        # # #

        # Eager fan-out: taken[k] records that source k already took the current sink sample.
        # Source valid is sink valid masked by taken (never by a ready), and the sink sample is
        # consumed once every source has taken it (before or in this cycle).
        taken = Signal(n)
        done  = Signal(n)
        for k, s in enumerate(self.sources):
            self.comb += [
                *self.sink.connect(s, omit={"valid", "ready"}),  # Payload + first/last.
                s.valid.eq(self.sink.valid & ~taken[k]),
                done[k].eq(taken[k] | s.ready),
            ]
        self.comb += self.sink.ready.eq(done == (2**n - 1))
        self.sync += If(self.sink.valid,
            If(self.sink.ready,
                taken.eq(0),
            ).Else(
                taken.eq(done),
            )
        )
