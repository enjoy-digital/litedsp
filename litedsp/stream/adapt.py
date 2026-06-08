#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Clock-domain crossing and width adaptation for I/Q streams (thin wrappers over LiteX)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import iq_layout

# Clock-Domain Crossing ----------------------------------------------------------------------------

class IQClockDomainCrossing(LiteXModule):
    """Cross an I/Q stream between clock domains via a LiteX async FIFO."""
    def __init__(self, cd_from="sys", cd_to="sys", data_width=16, depth=8):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.cdc = stream.ClockDomainCrossing(iq_layout(data_width),
            cd_from=cd_from, cd_to=cd_to, depth=depth)
        self.comb += [
            self.sink.connect(self.cdc.sink),
            self.cdc.source.connect(self.source),
        ]
