#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Trivial combinational I/Q stream maps (zero latency)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import iq_layout

# Helpers ------------------------------------------------------------------------------------------

class _IQMap(LiteXModule):
    """Base: combinational I/Q passthrough with handshake; subclass sets i/q expressions."""
    def __init__(self, data_width=16):
        self.data_width = data_width
        self.latency    = 0
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        # # #
        self.comb += [
            self.source.valid.eq(self.sink.valid),
            self.sink.ready.eq(self.source.ready),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
            self.source.i.eq(self.map_i()),
            self.source.q.eq(self.map_q()),
        ]

    def map_i(self): return self.sink.i
    def map_q(self): return self.sink.q

# Operations ---------------------------------------------------------------------------------------

class Conjugate(_IQMap):
    """Complex conjugate: ``q -> -q``."""
    def map_q(self): return -self.sink.q

class SwapIQ(_IQMap):
    """Swap I and Q (a +/-90 deg rotation / spectrum mirror)."""
    def map_i(self): return self.sink.q
    def map_q(self): return self.sink.i

class Negate(_IQMap):
    """Negate both components."""
    def map_i(self): return -self.sink.i
    def map_q(self): return -self.sink.q
