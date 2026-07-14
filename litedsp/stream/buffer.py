#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import iq_layout

# Skid Buffer --------------------------------------------------------------------------------------

class LiteDSPSkidBuffer(LiteXModule):
    """Elastic timing-slack buffer for an I/Q stream (registers both valid and ready paths).

    Inserts a pipeline stage on both the valid/payload and ready paths so a long combinational
    path can be cut without losing throughput. Thin wrapper over ``stream.Buffer``.
    """
    def __init__(self, data_width=16):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.latency = 0  # Elastic: no sample-index offset.

        # # #

        self.buffer = stream.Buffer(iq_layout(data_width), pipe_valid=True, pipe_ready=True)
        self.comb += [
            self.sink.connect(self.buffer.sink),
            self.buffer.source.connect(self.source),
        ]
