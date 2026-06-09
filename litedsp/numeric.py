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
    """Unsigned integer square root (floor), restoring algorithm.

    For an ``in_width``-bit input the result is ``ceil(in_width/2)`` bits. Two implementations,
    same numeric result:

    - ``pipelined=True`` (default): one combinational stage per result bit, output registered
      (``latency = 1``, 1 sample/cycle) — for streaming use.
    - ``pipelined=False``: one stage reused over ``out_width`` cycles (``latency = out_width``,
      far smaller) — for low-rate use such as RMS, which emits only once per window.

    Used by RMS / vector-norm.
    """
    def __init__(self, in_width=32, pipelined=True, with_csr=True):
        self.in_width  = in_width
        self.out_width = (in_width + 1)//2
        self.pipelined = pipelined
        R   = self.out_width
        self.sink   = stream.Endpoint([("data", in_width)])
        self.source = stream.Endpoint([("data", R)])

        # # #

        if pipelined:
            self.latency = 1
            adv = Signal()
            self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]
            x   = self.sink.data
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
            self.sync += If(adv,
                self.source.data.eq(prev_res),
                self.source.valid.eq(self.sink.valid),
            )
            return

        # Sequential: one restoring stage reused over R cycles.
        self.latency = R
        x    = Signal(in_width)
        rem  = Signal(in_width + 2)
        res  = Signal(R)
        i    = Signal(max=R)
        two  = Signal(2)
        rem_new = Signal(in_width + 2)
        trial   = Signal(in_width + 2)
        ge      = Signal()
        self.comb += [
            two.eq((x >> (2*i)) & 0b11),
            rem_new.eq((rem << 2) | two),
            trial.eq((res << 2) | 1),
            ge.eq(rem_new >= trial),
        ]
        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                NextValue(x, self.sink.data),
                NextValue(rem, 0), NextValue(res, 0), NextValue(i, R - 1),
                NextState("RUN"),
            )
        )
        fsm.act("RUN",
            NextValue(rem, Mux(ge, rem_new - trial, rem_new)),
            NextValue(res, (res << 1) | ge),
            If(i == 0, NextState("DONE")).Else(NextValue(i, i - 1)),
        )
        fsm.act("DONE",
            self.source.valid.eq(1),
            self.source.data.eq(res),
            If(self.source.ready, NextState("IDLE")),
        )
