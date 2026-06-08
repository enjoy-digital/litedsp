#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import iq_layout

# Symbol Slicer ------------------------------------------------------------------------------------

@ResetInserter()
class Slicer(LiteXModule):
    """Hard-decision QAM slicer: map each of I/Q to the nearest PAM level.

    ``bits_per_axis`` sets ``L = 2**bits_per_axis`` levels per axis at positions
    ``(2k-(L-1))*spacing``. Emits the decided constellation point on ``source`` (I/Q) and the
    symbol index on ``source.symbol`` (``[q_bits | i_bits]``). QPSK = ``bits_per_axis=1``,
    16-QAM = ``2``.
    """
    def __init__(self, data_width=16, bits_per_axis=1, spacing=8192, with_csr=True):
        self.bits_per_axis = bits_per_axis
        L = 1 << bits_per_axis
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint([
            ("i", (data_width, True)), ("q", (data_width, True)),
            ("symbol", 2*bits_per_axis),
        ])
        self.latency = 1

        # # #

        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        def decide(x):
            # k = number of decision boundaries (at (2j-L+2)*spacing) at/below x.
            k = Signal(max=max(2, L))
            count = sum((x >= ((2*j - L + 2)*spacing)) for j in range(L - 1))
            self.comb += k.eq(count)
            point = Signal((data_width, True))
            self.comb += point.eq((2*k - (L - 1))*spacing)
            return k, point

        ki, pi = decide(self.sink.i)
        kq, pq = decide(self.sink.q)
        self.sync += If(adv,
            self.source.i.eq(pi), self.source.q.eq(pq),
            self.source.symbol.eq(Cat(ki, kq)),
            self.source.valid.eq(self.sink.valid),
        )
