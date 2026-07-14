#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled

# Saturate -----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSaturate(LiteXModule):
    """Rescale a complex I/Q stream by a fixed right ``shift`` with round-half-up + saturation.

    A thin standalone wrapper around the shared fixed-point helpers, useful as an explicit
    level/scaling stage between blocks. ``shift = 0`` makes it a pure saturating passthrough.
    ``sat`` is a sticky overflow flag (cleared by ``clear_sat``).
    """
    def __init__(self, data_width=16, in_width=None, shift=0, with_csr=True):
        if in_width is None:
            in_width = data_width
        self.data_width = data_width
        self.in_width   = in_width
        self.shift      = shift
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(in_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.clear_sat = Signal()
        self.sat       = Signal()

        # # #

        adv = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
        ]

        res_i, ovf_i = scaled(self.sink.i, shift, data_width)
        res_q, ovf_q = scaled(self.sink.q, shift, data_width)
        self.sync += If(adv,
            self.source.i.eq(res_i),
            self.source.q.eq(res_q),
            self.source.valid.eq(self.sink.valid),
        )
        self.sync += [
            If(self.clear_sat,
                self.sat.eq(0),
            ).Elif(self.sink.valid & adv & (ovf_i | ovf_q),
                self.sat.eq(1),
            )
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("clear_sat", size=1, offset=0, pulse=True, description="Clear saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturation", size=1, description="Output saturated since last clear."),
        ])
        self.comb += [
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.saturation.eq(self.sat),
        ]
