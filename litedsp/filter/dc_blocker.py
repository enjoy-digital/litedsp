#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, saturated

# DC Blocker ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDCBlocker(LiteXModule):
    """Multiplier-free 1st-order DC-removal IIR (per I/Q).

    ``y[n] = x[n] - x[n-1] + y[n-1] - (y[n-1] >> pole_shift)`` (pole at ``1 - 2**-pole_shift``,
    a notch at DC). Larger ``pole_shift`` -> notch closer to DC (slower settling). The feedback
    state is saturated for stability.
    """
    def __init__(self, data_width=16, pole_shift=5, with_csr=True):
        self.data_width = data_width
        self.pole_shift = pole_shift
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        for field in ["i", "q"]:
            x      = getattr(self.sink, field)
            x_prev = Signal((data_width, True))
            y_prev = Signal((data_width, True))
            y_next = Signal((data_width, True))
            self.comb += y_next.eq(saturated(x - x_prev + y_prev - (y_prev >> pole_shift), data_width))
            self.sync += If(xfer,
                x_prev.eq(x),
                y_prev.eq(y_next),
            )
            self.sync += If(adv, getattr(self.source, field).eq(y_next))

        valid_pipe = Signal()
        self.sync += If(adv, valid_pipe.eq(self.sink.valid))
        self.comb += self.source.valid.eq(valid_pipe)
