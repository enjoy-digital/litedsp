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
    """Delay a stream by ``depth`` cycles (payload and valid travel together).

    A simple pipeline of register stages used to time-align parallel branches by a known
    latency. Under backpressure all branches stall identically, so the alignment in samples is
    preserved. ``depth = 0`` is a passthrough.

    Parameters
    ----------
    depth : int
        Delay in samples (>= 0; 0 = pure passthrough). Costs one payload register stage
        (payload width + 1 flip-flops) per unit of delay.
    layout : list
        Payload layout (default ``iq_layout(data_width)``); any layout works (real, TDM, abc).
    """
    def __init__(self, depth=1, data_width=16, layout=None):
        check(depth >= 0, "expected depth >= 0")
        if layout is None:
            layout = iq_layout(data_width)
        self.depth   = depth
        self.latency = depth
        self.sink   = stream.Endpoint(layout)
        self.source = stream.Endpoint(layout)

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
        p_pipe = [Signal(len(self.sink.payload)) for _ in range(depth)]  # Raw payload bits.
        v_pipe = Signal(depth)
        # depth == 1 shifts valid alone (an empty v_pipe[:-1] slice emits illegal Verilog —
        # found by the full-registry Verilator lint sweep).
        v_next = self.sink.valid if depth == 1 else Cat(self.sink.valid, v_pipe[:-1])
        self.sync += If(adv,
            p_pipe[0].eq(self.sink.payload.raw_bits()),
            v_pipe.eq(v_next),
            *[p_pipe[k].eq(p_pipe[k - 1]) for k in range(1, depth)],
        )

        # Output.
        # -------
        self.comb += [
            self.source.valid.eq(v_pipe[-1]),
            self.source.payload.raw_bits().eq(p_pipe[-1]),
        ]
