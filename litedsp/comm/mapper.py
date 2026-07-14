#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import iq_layout

# Symbol Mapper ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSymbolMapper(LiteXModule):
    """Map a QAM symbol index to a constellation I/Q point (inverse of :class:`LiteDSPSlicer`).

    ``bits_per_axis`` gives ``L = 2**bits_per_axis`` PAM levels per axis at
    ``(2k-(L-1))*spacing``. ``sink.symbol`` is ``[q_bits | i_bits]``. QPSK = ``1``, 16-QAM = ``2``.
    """
    def __init__(self, data_width=16, bits_per_axis=1, spacing=8192, with_csr=True):
        self.bits_per_axis = bits_per_axis
        L = 1 << bits_per_axis
        self.sink   = stream.Endpoint([("symbol", 2*bits_per_axis)])
        self.source = stream.Endpoint(iq_layout(data_width))
        self.latency = 1

        # # #

        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]
        ki = self.sink.symbol[:bits_per_axis]
        kq = self.sink.symbol[bits_per_axis:]
        self.sync += If(adv,
            self.source.i.eq((2*ki - (L - 1))*spacing),
            self.source.q.eq((2*kq - (L - 1))*spacing),
            self.source.valid.eq(self.sink.valid),
        )
