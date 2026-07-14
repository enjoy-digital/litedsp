#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, rounded

# Moving Average -----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPMovingAverage(LiteXModule):
    """Boxcar moving average over ``2**length_log2`` samples (per I/Q), a.k.a. CIC-1.

    Maintains a running sum ``acc += x[n] - x[n-L]`` with an L-deep delay line (single adder),
    and outputs the rounded average ``acc / L``. Output stays in the input range, so no
    saturation is needed.
    """
    def __init__(self, data_width=16, length_log2=4, with_csr=True):
        assert length_log2 >= 1
        L = 1 << length_log2
        self.data_width  = data_width
        self.length_log2 = length_log2
        self.latency     = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        acc_width = data_width + length_log2 + 1
        for field in ["i", "q"]:
            x   = getattr(self.sink, field)
            mem = Memory(data_width, L)
            wp  = mem.get_port(write_capable=True)
            rp  = mem.get_port(async_read=True)
            self.specials += mem, wp, rp
            ptr = Signal(max=L)
            old = Signal((data_width, True))
            acc = Signal((acc_width, True))
            acc_next = Signal((acc_width, True))
            self.comb += [
                rp.adr.eq(ptr), wp.adr.eq(ptr),
                old.eq(rp.dat_r),
                acc_next.eq(acc + x - old),
                wp.dat_w.eq(x), wp.we.eq(xfer),
            ]
            self.sync += If(xfer,
                acc.eq(acc_next),
                If(ptr == (L - 1), ptr.eq(0)).Else(ptr.eq(ptr + 1)),
            )
            self.sync += If(adv, getattr(self.source, field).eq(rounded(acc_next, length_log2)))

        valid_pipe = Signal()
        self.sync += If(adv, valid_pipe.eq(self.sink.valid))
        self.comb += self.source.valid.eq(valid_pipe)
