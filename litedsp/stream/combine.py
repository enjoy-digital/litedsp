#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math

from functools import reduce
from operator  import and_

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, saturated

# Combine ------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCombine(LiteXModule):
    """Sum ``n_channels`` complex I/Q streams into one, with per-channel enable and saturation.

    The internal accumulator grows to fit the worst-case sum (``data_width + ceil(log2(N))``)
    so it never wraps, then the result is saturated back to ``data_width`` — unlike the
    original tetra ``Sum`` which could silently overflow. All enabled inputs are consumed
    together (synchronous join); output appears after a fixed 1-cycle latency.

    Parameters
    ----------
    n_channels : int
        Number of input streams summed (>= 1). Adds ceil(log2(n_channels)) accumulator
        guard bits before saturation; all inputs must present a sample for any to transfer.
    layout : list
        Payload layout (default ``iq_layout(data_width)``): every signed payload field is
        summed (``real_layout``/``abc_layout`` work too); unsigned tags (TDM ``channel``) are
        rejected because a sum of tagged beats has no meaning.
    """
    def __init__(self, n_channels=2, data_width=16, with_csr=True, layout=None):
        check(n_channels >= 1, "expected n_channels >= 1")
        if layout is None:
            layout = iq_layout(data_width)
        fields = [(name, shape) for name, shape, *_ in layout]
        check(all(isinstance(s, tuple) and s[1] for _, s in fields),
            "expected a layout of signed sample fields (no tags such as 'channel')")
        self.n_channels = n_channels
        self.data_width = data_width
        self.latency    = 1
        self.sinks  = [stream.Endpoint(layout) for _ in range(n_channels)]
        self.source = stream.Endpoint(layout)
        self.enable = Signal(n_channels, reset=2**n_channels - 1)  # Per-channel enable mask.

        # # #

        # Synchronous join: consume all sinks together when output can accept.
        # --------------------------------------------------------------------
        all_valid = reduce(and_, [s.valid for s in self.sinks])
        advance   = Signal()  # Output register can accept a new sample.
        consume   = Signal()  # All sinks transfer together this cycle.
        self.comb += [
            advance.eq(self.source.ready | ~self.source.valid),
            consume.eq(all_valid & advance),
        ]
        for s in self.sinks:
            self.comb += s.ready.eq(consume)

        # Width-growing sum of enabled channels, then saturate.
        # -----------------------------------------------------
        # Disabled channels contribute zero but are still consumed (the join stays in lockstep).
        guard = int(math.ceil(math.log2(n_channels))) if n_channels > 1 else 0
        for name, (width, _) in fields:
            acc = Signal((width + guard, True), name=f"sum_{name}")
            self.comb += acc.eq(reduce(lambda a, b: a + b,
                [Mux(self.enable[k], getattr(self.sinks[k], name), 0) for k in range(n_channels)]))
            self.sync += If(advance, getattr(self.source, name).eq(saturated(acc, width)))
        self.sync += If(advance, self.source.valid.eq(all_valid))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._enable = CSRStorage(self.n_channels, reset=2**self.n_channels - 1, name="enable",
            description="Per-channel enable mask (bit k enables channel k).")
        self.comb += self.enable.eq(self._enable.storage)
