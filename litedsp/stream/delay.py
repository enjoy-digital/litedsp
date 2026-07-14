#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import check, iq_layout

# Delay / Align ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDelay(LiteXModule):
    """Delay an I/Q stream by ``depth`` cycles (data and valid travel together).

    A simple pipeline of register stages used to time-align parallel branches by a known
    latency. Under backpressure all branches stall identically, so the alignment in samples is
    preserved. ``depth = 0`` is a passthrough.

    Parameters
    ----------
    depth : int
        Delay in samples (>= 0; 0 = pure passthrough). Costs one I/Q register stage
        (2*data_width + 1 flip-flops) per unit of delay.
    """
    def __init__(self, depth=1, data_width=16):
        check(depth >= 0, "expected depth >= 0")
        self.depth   = depth
        self.latency = depth
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Passthrough.
        # ------------
        if depth == 0:
            self.comb += self.sink.connect(self.source)
            return

        # Handshake.
        # ----------
        adv = Signal()  # Pipeline advances (output slot free or being consumed).
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        # Delay Pipeline.
        # ---------------
        # Data and valid shift together, so input bubbles travel through and reappear at the
        # output with the sample alignment unchanged.
        i_pipe = [Signal((data_width, True)) for _ in range(depth)]
        q_pipe = [Signal((data_width, True)) for _ in range(depth)]
        v_pipe = Signal(depth)
        self.sync += If(adv,
            i_pipe[0].eq(self.sink.i),
            q_pipe[0].eq(self.sink.q),
            v_pipe.eq(Cat(self.sink.valid, v_pipe[:-1])),
            *[i_pipe[k].eq(i_pipe[k - 1]) for k in range(1, depth)],
            *[q_pipe[k].eq(q_pipe[k - 1]) for k in range(1, depth)],
        )

        # Output.
        # -------
        self.comb += [
            self.source.valid.eq(v_pipe[-1]),
            self.source.i.eq(i_pipe[-1]),
            self.source.q.eq(q_pipe[-1]),
        ]
