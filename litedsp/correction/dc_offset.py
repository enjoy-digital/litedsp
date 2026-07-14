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

# DC Offset Correction -----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDCOffset(LiteXModule):
    """Estimate and remove a DC offset per I/Q with a leaky-integrator mean.

    ``mean += (x - mean) >> mu`` (pole ``1 - 2**-mu``); output ``x - round(mean)``. Larger
    ``mu`` = slower/finer estimate. The current estimates are exposed (``mean_i``/``mean_q``)
    for monitoring; this is the adaptive cousin of the multiplier-free DC blocker.
    """
    def __init__(self, data_width=16, mu=10, with_csr=True):
        self.data_width = data_width
        self.mu     = mu
        self.latency = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.mean_i = Signal((data_width + mu, True))  # DC estimate accumulator (mu fractional bits).
        self.mean_q = Signal((data_width + mu, True))  # DC estimate accumulator (mu fractional bits).

        # # #

        # Handshake.
        # ----------
        adv  = Signal()  # Pipeline drains (output slot free or being consumed).
        xfer = Signal()  # A sample is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath.
        # ---------
        for field, mean in [("i", self.mean_i), ("q", self.mean_q)]:
            x   = getattr(self.sink, field)
            est = Signal((data_width, True))
            self.comb += est.eq(mean >> self.mu)                 # round-toward-zero estimate.
            self.sync += If(xfer, mean.eq(mean + (x - est)))     # Estimate tracks accepted samples only.
            self.sync += If(adv,
                getattr(self.source, field).eq(saturated(x - est, data_width)),  # Subtract grows 1 bit; saturate.
            )

        # Output.
        # -------
        valid = Signal()
        self.sync += If(adv, valid.eq(self.sink.valid))
        self.comb += self.source.valid.eq(valid)
