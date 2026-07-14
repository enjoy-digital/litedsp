#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import real_layout

# Peak-Bin Finder ----------------------------------------------------------------------------------

class LiteDSPPeakBin(LiteXModule):
    """Argmax over a framed real stream (e.g. a PSD/FFT-magnitude frame).

    Tracks the maximum value and its index within each frame (delimited by ``sink.first`` /
    ``sink.last``) and emits ``(index, value)`` on ``source`` when the frame ends.
    """
    def __init__(self, data_width=32, index_width=12, with_csr=True):
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint([("index", index_width), ("value", data_width)])
        self.latency = 1

        # # #

        idx      = Signal(index_width)
        best_idx = Signal(index_width)
        best_val = Signal(data_width)
        self.comb += self.sink.ready.eq(self.source.ready | ~self.source.valid)
        xfer = Signal()
        self.comb += xfer.eq(self.sink.valid & self.sink.ready)

        cur_better = Signal()
        self.comb += cur_better.eq(self.sink.first | (self.sink.data > best_val))
        new_idx = Signal(index_width)
        new_val = Signal(data_width)
        self.comb += [
            new_idx.eq(Mux(cur_better, idx, best_idx)),
            new_val.eq(Mux(cur_better, self.sink.data, best_val)),
        ]
        self.sync += [
            If(self.source.valid & self.source.ready, self.source.valid.eq(0)),
            If(xfer,
                best_idx.eq(new_idx),
                best_val.eq(new_val),
                idx.eq(Mux(self.sink.last, 0, idx + 1)),
                If(self.sink.last,
                    self.source.index.eq(new_idx),
                    self.source.value.eq(new_val),
                    self.source.valid.eq(1),
                )
            )
        ]
