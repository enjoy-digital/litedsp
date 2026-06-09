#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Loopback measurement taps: compare a reference stream against a received stream.

``ErrorCounter`` synchronously joins a reference and a received I/Q stream, counts how many
samples differ (symbol/sample error rate), and exposes the error + total counts over CSR. Pair
it with :class:`litedsp.generation.pattern.PatternSource` (PRBS) feeding both a chain-under-test
and the reference to get a self-checking loopback for bring-up.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

# Error Counter ------------------------------------------------------------------------------------

class ErrorCounter(LiteXModule):
    """Count mismatches between a reference and a received I/Q stream (synchronous join)."""
    def __init__(self, data_width=16, with_csr=True):
        self.sink_ref = stream.Endpoint(iq_layout(data_width))
        self.sink_rx  = stream.Endpoint(iq_layout(data_width))
        self.errors = Signal(32)
        self.total  = Signal(32)
        self.clear  = Signal()

        # # #

        # Consume a pair only when both inputs are valid (lock-step comparison).
        consume = Signal()
        self.comb += [
            consume.eq(self.sink_ref.valid & self.sink_rx.valid),
            self.sink_ref.ready.eq(consume),
            self.sink_rx.ready.eq(consume),
        ]
        mismatch = Signal()
        self.comb += mismatch.eq((self.sink_ref.i != self.sink_rx.i) |
                                 (self.sink_ref.q != self.sink_rx.q))
        self.sync += [
            If(self.clear,
                self.errors.eq(0),
                self.total.eq(0),
            ).Elif(consume,
                self.total.eq(self.total + 1),
                If(mismatch, self.errors.eq(self.errors + 1)),
            )
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._errors = CSRStatus(32, name="errors", description="Mismatched samples since clear.")
        self._total  = CSRStatus(32, name="total",  description="Compared samples since clear.")
        self._clear  = CSRStorage(1, name="clear",  description="Reset the counters.", pulse=True)
        self.comb += [
            self._errors.status.eq(self.errors),
            self._total.status.eq(self.total),
            self.clear.eq(self._clear.storage),
        ]
