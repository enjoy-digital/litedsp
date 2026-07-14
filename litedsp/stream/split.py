#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from functools import reduce
from operator  import and_

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import check, iq_layout

# Split / Duplicate --------------------------------------------------------------------------------

class LiteDSPSplit(LiteXModule):
    """Fan-out one I/Q stream to ``n`` identical sources (all consumed together)."""
    def __init__(self, n=2, data_width=16):
        check(n >= 1, "expected n >= 1")
        self.n      = n
        self.latency = 0
        self.sink    = stream.Endpoint(iq_layout(data_width))
        self.sources = [stream.Endpoint(iq_layout(data_width)) for _ in range(n)]

        # # #

        # Atomic fan-out: valid is gated by all_ready so every source sees exactly the same
        # transfers (a fast branch cannot consume a sample the slow branches have not accepted).
        all_ready = reduce(and_, [s.ready for s in self.sources])
        self.comb += self.sink.ready.eq(all_ready)
        for s in self.sources:
            self.comb += [
                s.valid.eq(self.sink.valid & all_ready),
                s.first.eq(self.sink.first),
                s.last.eq(self.sink.last),
                s.i.eq(self.sink.i),
                s.q.eq(self.sink.q),
            ]
