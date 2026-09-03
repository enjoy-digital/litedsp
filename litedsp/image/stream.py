#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Pixel stream plumbing: the elastic pixel FIFO."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common      import check, pixel_layout
from litedsp.stream.fifo import LiteDSPStreamFIFO

# Pixel FIFO ---------------------------------------------------------------------------------------

class LiteDSPPixelFIFO(LiteXModule):
    """Elastic buffer for a pixel stream (``pixel_layout``, tags carried).

    A thin wrapper over :class:`LiteDSPStreamFIFO` with the pixel layout: the buffer a parallel
    branch needs to run at least ``kernel.latency`` beats ahead of a 2-D block before a
    lock-step join (a line-buffer branch delays by ``P * width`` beats). Exposes ``level`` and the
    sticky ``overflow`` flag; latency 0 (first-word fall-through).
    """
    def __init__(self, depth=1024, data_width=8, n_channels=3, with_csr=True):
        check(depth >= 2, "expected depth >= 2")
        self.depth      = depth
        self.data_width = data_width
        self.n_channels = n_channels
        self.latency    = 0
        layout = pixel_layout(data_width, n_channels)
        self.fifo   = LiteDSPStreamFIFO(depth=depth, layout=layout, with_csr=False)
        self.sink, self.source = self.fifo.sink, self.fifo.source
        self.level    = self.fifo.level
        self.overflow = self.fifo.overflow

        # # #

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._level  = CSRStatus(len(self.level), name="level", description="Pixels buffered.")
        self._status = CSRStatus(fields=[
            CSRField("overflow", size=1, offset=0, description="Sticky: a pixel was dropped (sink stalled)."),
        ])
        self.comb += [self._level.status.eq(self.level), self._status.fields.overflow.eq(self.overflow)]
