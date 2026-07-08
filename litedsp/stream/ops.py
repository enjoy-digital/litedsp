#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Trivial combinational I/Q stream maps and element-wise operations (zero latency)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import iq_layout, saturated

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

# Two-input operations -----------------------------------------------------------------------------

class IQAdd(LiteXModule):
    """Saturating complex adder: ``source = a + b`` (e.g. signal + noise test paths).

    Joint handshake: a transfer needs both inputs valid (both advance together). The sums are
    saturated to full scale per the fixed-point convention. ``first``/``last`` follow ``sink_a``.
    """
    def __init__(self, data_width=16):
        self.data_width = data_width
        self.latency    = 0
        self.sink_a = stream.Endpoint(iq_layout(data_width))
        self.sink_b = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        xfer = Signal()
        self.comb += [
            self.source.valid.eq(self.sink_a.valid & self.sink_b.valid),
            xfer.eq(self.source.valid & self.source.ready),
            self.sink_a.ready.eq(xfer),
            self.sink_b.ready.eq(xfer),
            self.source.first.eq(self.sink_a.first),
            self.source.last.eq(self.sink_a.last),
            self.source.i.eq(saturated(self.sink_a.i + self.sink_b.i, data_width)),
            self.source.q.eq(saturated(self.sink_a.q + self.sink_b.q, data_width)),
        ]
