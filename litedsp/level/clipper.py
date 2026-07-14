#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

# Clipper / Limiter --------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPClipper(LiteXModule):
    """Hard limiter: clamp each of I/Q to +/- ``threshold`` (runtime). ``clip`` flags a clip."""
    def __init__(self, data_width=16, with_csr=True):
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.threshold = Signal(data_width, reset=(1 << (data_width - 1)) - 1)
        self.clip      = Signal()

        # # #

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        # Clipping Datapath.
        # ------------------
        thr  = Signal((data_width + 1, True))
        self.comb += thr.eq(self.threshold)
        clipped = Signal()
        for field in ["i", "q"]:
            x = getattr(self.sink, field)
            c = Signal((data_width, True))
            over = Signal()
            self.comb += [
                over.eq((x > thr) | (x < -thr)),
                c.eq(Mux(x > thr, thr, Mux(x < -thr, -thr, x))),
            ]
            self.comb += If(over, clipped.eq(1))
            self.sync += If(adv, getattr(self.source, field).eq(c))

        # Output.
        # -------
        valid = Signal()
        self.sync += If(adv, valid.eq(self.sink.valid), self.clip.eq(self.sink.valid & clipped))
        self.comb += self.source.valid.eq(valid)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._threshold = CSRStorage(self.data_width, reset=(1 << (self.data_width - 1)) - 1,
            name="threshold", description="Clip threshold (magnitude).")
        self._status = CSRStatus(fields=[CSRField("clip", size=1, description="Clipping occurred.")])
        self.comb += [self.threshold.eq(self._threshold.storage), self._status.fields.clip.eq(self.clip)]
