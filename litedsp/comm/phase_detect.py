#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common            import iq_layout, real_layout
from litedsp.generation.cordic import LiteDSPCORDIC

# Phase Detector -----------------------------------------------------------------------------------

class LiteDSPPhaseDetect(LiteXModule):
    """Instantaneous phase ``atan2(Q, I)`` of an I/Q stream (CORDIC vectoring).

    Building block for carrier/timing loops. Output is the angle in signed phase units
    (full circle = 2**angle_width).

    Parameters
    ----------
    angle_width : int
        Output angle resolution in bits (full circle = 2**angle_width); sets the CORDIC
        stage count, so latency and resources grow with it.
    """
    def __init__(self, data_width=16, angle_width=16, with_csr=True):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint([("angle", (angle_width, True))])

        # # #

        self.cordic = LiteDSPCORDIC(data_width=data_width, angle_width=angle_width,
            mode="vectoring", with_csr=False)
        self.latency = self.cordic.latency
        self.comb += [
            self.cordic.sink.valid.eq(self.sink.valid),
            self.cordic.sink.x.eq(self.sink.i),
            self.cordic.sink.y.eq(self.sink.q),
            self.sink.ready.eq(self.cordic.sink.ready),
            self.source.valid.eq(self.cordic.source.valid),
            self.source.angle.eq(self.cordic.source.angle),
            self.cordic.source.ready.eq(self.source.ready),
        ]
