#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Sample-format converters (combinational, zero latency)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import iq_layout

# Offset-Binary <-> Two's-Complement ---------------------------------------------------------------

class LiteDSPOffsetBinaryToTwos(LiteXModule):
    """Convert unsigned offset-binary I/Q samples to signed two's-complement (flip the MSB)."""
    def __init__(self, data_width=16):
        self.latency = 0
        self.sink   = stream.Endpoint([("i", data_width), ("q", data_width)])    # Unsigned.
        self.source = stream.Endpoint(iq_layout(data_width))                     # Signed.
        # # #
        msb = 1 << (data_width - 1)
        self.comb += [
            self.source.valid.eq(self.sink.valid), self.sink.ready.eq(self.source.ready),
            self.source.first.eq(self.sink.first), self.source.last.eq(self.sink.last),
            self.source.i.eq(self.sink.i ^ msb),
            self.source.q.eq(self.sink.q ^ msb),
        ]

class LiteDSPTwosToOffsetBinary(LiteXModule):
    """Convert signed two's-complement I/Q samples to unsigned offset-binary (flip the MSB)."""
    def __init__(self, data_width=16):
        self.latency = 0
        self.sink   = stream.Endpoint(iq_layout(data_width))                     # Signed.
        self.source = stream.Endpoint([("i", data_width), ("q", data_width)])    # Unsigned.
        # # #
        msb = 1 << (data_width - 1)
        self.comb += [
            self.source.valid.eq(self.sink.valid), self.sink.ready.eq(self.source.ready),
            self.source.first.eq(self.sink.first), self.source.last.eq(self.sink.last),
            self.source.i.eq(self.sink.i ^ msb),
            self.source.q.eq(self.sink.q ^ msb),
        ]
