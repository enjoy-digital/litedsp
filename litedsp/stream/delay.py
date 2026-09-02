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
        Delay in samples (>= 0; 0 = pure passthrough). Costs one register stage per payload
        field (payload width + 1 flip-flops) per unit of delay.
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
        # One register chain per payload field (the netlist the closed timing targets of the
        # DDC/DUC cores were recorded against; a single concatenated pipe perturbs synthesis).
        fields = [name for name, *_ in layout]
        pipes  = {name: [Signal(shape) for _ in range(depth)] for name, shape, *_ in layout}
        v_pipe = Signal(depth)
        # depth == 1 shifts valid alone (an empty v_pipe[:-1] slice emits illegal Verilog —
        # found by the full-registry Verilator lint sweep).
        v_next = self.sink.valid if depth == 1 else Cat(self.sink.valid, v_pipe[:-1])
        self.sync += If(adv,
            *[pipes[name][0].eq(getattr(self.sink, name)) for name in fields],
            v_pipe.eq(v_next),
            *[pipes[name][k].eq(pipes[name][k - 1]) for name in fields for k in range(1, depth)],
        )

        # Output.
        # -------
        self.comb += [
            self.source.valid.eq(v_pipe[-1]),
            *[getattr(self.source, name).eq(pipes[name][-1]) for name in fields],
        ]
