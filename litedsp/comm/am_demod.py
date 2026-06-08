#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common             import iq_layout, real_layout
from litedsp.analysis.magnitude import Magnitude

# AM Demodulator -----------------------------------------------------------------------------------

class AMDemod(LiteXModule):
    """AM envelope demodulator: ``|x|`` (magnitude) with the carrier DC removed.

    A :class:`Magnitude` followed by a multiplier-free 1st-order DC blocker (pole
    ``1 - 2**-pole_shift``). Output is the recovered modulating signal (signed).
    """
    def __init__(self, data_width=16, pole_shift=8, with_csr=True):
        self.sink = stream.Endpoint(iq_layout(data_width))

        # # #

        self.mag = Magnitude(data_width=data_width, with_csr=False)
        W        = self.mag.out_width + 1
        self.source = stream.Endpoint(real_layout(W))
        self.latency = self.mag.latency + 1
        self.comb += self.sink.connect(self.mag.sink)

        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.mag.source.ready.eq(adv)]

        x      = Signal((W, True))
        x_prev = Signal((W, True))
        y_prev = Signal((W, True))
        y_next = Signal((W, True))
        self.comb += [
            x.eq(self.mag.source.data),
            y_next.eq(x - x_prev + y_prev - (y_prev >> pole_shift)),
        ]
        self.sync += If(adv,
            x_prev.eq(x),
            y_prev.eq(y_next),
            self.source.data.eq(y_next),
            self.source.valid.eq(self.mag.source.valid),
        )
