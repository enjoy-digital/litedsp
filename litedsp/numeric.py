#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

# Integer Square Root ------------------------------------------------------------------------------

@ResetInserter()
class ISqrt(LiteXModule):
    """Unsigned integer square root (floor), unrolled restoring algorithm.

    One combinational stage per result bit, output registered (``latency = 1``). For an
    ``in_width``-bit input the result is ``ceil(in_width/2)`` bits. Used by RMS / vector-norm.
    """
    def __init__(self, in_width=32, with_csr=True):
        self.in_width  = in_width
        self.out_width = (in_width + 1)//2
        self.latency   = 1
        self.sink   = stream.Endpoint([("data", in_width)])
        self.source = stream.Endpoint([("data", self.out_width)])

        # # #

        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        R   = self.out_width
        x   = self.sink.data
        rem = Signal(in_width + 2)
        res = Signal(R)
        prev_rem, prev_res = Constant(0), Constant(0)
        for s in range(R):
            i        = R - 1 - s
            two      = (x >> (2*i)) & 0b11
            rem_new  = Signal(in_width + 2)
            trial    = Signal(in_width + 2)
            ge       = Signal()
            cur_rem  = Signal(in_width + 2)
            cur_res  = Signal(R)
            self.comb += [
                rem_new.eq((prev_rem << 2) | two),
                trial.eq((prev_res << 2) | 1),
                ge.eq(rem_new >= trial),
                cur_rem.eq(Mux(ge, rem_new - trial, rem_new)),
                cur_res.eq((prev_res << 1) | ge),
            ]
            prev_rem, prev_res = cur_rem, cur_res
        self.comb += [rem.eq(prev_rem), res.eq(prev_res)]
        self.sync += If(adv,
            self.source.data.eq(res),
            self.source.valid.eq(self.sink.valid),
        )
