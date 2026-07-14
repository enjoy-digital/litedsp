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

# Statistics ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPStats(LiteXModule):
    """Min / max / mean / variance of a real stream over ``2**window_log2`` samples.

    Emits one result per window on ``source`` (fields ``min, max, mean, variance``). Input is
    always accepted; the latest completed result is held until consumed.
    """
    def __init__(self, data_width=16, window_log2=8, with_csr=True):
        self.data_width  = data_width
        self.window_log2 = window_log2
        var_width   = 2*data_width
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint([
            ("min", (data_width, True)), ("max", (data_width, True)),
            ("mean", (data_width, True)), ("variance", var_width),
        ])
        self.latency = 1

        # # #

        N      = 1 << window_log2
        x      = self.sink.data
        count  = Signal(window_log2 + 1)
        acc    = Signal((data_width + window_log2 + 1, True))
        accsq  = Signal(2*data_width + window_log2)
        vmin   = Signal((data_width, True), reset=(1 << (data_width - 1)) - 1)
        vmax   = Signal((data_width, True), reset=-(1 << (data_width - 1)))
        last   = Signal()
        self.comb += [self.sink.ready.eq(1), last.eq(count == (N - 1))]

        meanf = Signal((data_width, True))
        self.comb += meanf.eq((acc + x) >> window_log2)
        self.sync += [
            If(self.source.valid & self.source.ready, self.source.valid.eq(0)),
            If(self.sink.valid,
                If(last,
                    self.source.min.eq(Mux(x < vmin, x, vmin)),
                    self.source.max.eq(Mux(x > vmax, x, vmax)),
                    self.source.mean.eq(meanf),
                    self.source.variance.eq(((accsq + x*x) >> window_log2) - meanf*meanf),
                    self.source.valid.eq(1),
                    acc.eq(0), accsq.eq(0), count.eq(0),
                    vmin.eq((1 << (data_width - 1)) - 1), vmax.eq(-(1 << (data_width - 1))),
                ).Else(
                    acc.eq(acc + x), accsq.eq(accsq + x*x), count.eq(count + 1),
                    If(x < vmin, vmin.eq(x)), If(x > vmax, vmax.eq(x)),
                )
            )
        ]
