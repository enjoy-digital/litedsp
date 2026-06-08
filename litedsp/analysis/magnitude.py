#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, real_layout

# Magnitude ----------------------------------------------------------------------------------------

@ResetInserter()
class Magnitude(LiteXModule):
    """Approximate complex magnitude ``|I + jQ|`` via alpha-max-beta-min.

    ``|z| ~= max(|I|, |Q|) + (min(|I|, |Q|) >> beta_shift)``. Cheap (no multiplier, no
    iteration); with the default ``beta_shift = 2`` (beta = 1/4) the error is within about
    -12%..0% of the true magnitude. For an exact magnitude use the CORDIC block in vectoring
    mode. The output is one bit wider than the input (magnitude can reach ~1.41x full scale).
    """
    def __init__(self, data_width=16, beta_shift=2, with_csr=True):
        self.data_width = data_width
        self.out_width  = data_width + 1
        self.beta_shift = beta_shift
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(real_layout(self.out_width))

        # # #

        adv = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
        ]

        # |I|, |Q| (one bit wider to hold the magnitude of the most-negative value).
        # ------------------------------------------------------------------------
        ai = Signal(data_width + 1)
        aq = Signal(data_width + 1)
        self.comb += [
            ai.eq(Mux(self.sink.i[-1], -self.sink.i, self.sink.i)),
            aq.eq(Mux(self.sink.q[-1], -self.sink.q, self.sink.q)),
        ]
        hi  = Signal(data_width + 1)
        lo  = Signal(data_width + 1)
        self.comb += [
            hi.eq(Mux(ai > aq, ai, aq)),
            lo.eq(Mux(ai > aq, aq, ai)),
        ]
        self.sync += If(adv,
            self.source.data.eq(hi + (lo >> beta_shift)),
            self.source.valid.eq(self.sink.valid),
        )
