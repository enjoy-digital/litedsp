#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Gray code mapping of symbol words (per lane)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check

# Gray Mapper --------------------------------------------------------------------------------------

class _LiteDSPGray(LiteXModule):
    def __init__(self, encode, width=2, n_lanes=1, with_csr=True):
        check(1 <= width <= 16 and 1 <= n_lanes <= 8,
              "expected 1 <= width <= 16, 1 <= n_lanes <= 8")
        self.width   = width
        self.n_lanes = n_lanes
        self.latency = 1
        self.sink   = stream.Endpoint([("data", n_lanes*width)])
        self.source = stream.Endpoint([("data", n_lanes*width)])

        # # #

        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]
        outs = []
        for k in range(n_lanes):
            b = self.sink.data[k*width:(k + 1)*width]
            if encode:
                g = Signal(width)
                self.comb += g.eq(b ^ (b >> 1))
            else:
                # Prefix XOR from the MSB down.
                bits = [Signal(name=f"d{k}_{i}") for i in range(width)]
                self.comb += bits[width - 1].eq(b[width - 1])
                for i in reversed(range(width - 1)):
                    self.comb += bits[i].eq(b[i] ^ bits[i + 1])
                g = Cat(*bits)
            outs.append(g)
        self.sync += If(adv,
            self.source.valid.eq(self.sink.valid), self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
            self.source.data.eq(Cat(*outs)),
        )
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("width",   size=5, offset=0, description="Bits per lane."),
            CSRField("n_lanes", size=4, offset=8, description="Lanes per beat."),
        ])
        self.comb += [self._config.fields.width.eq(self.width),
                      self._config.fields.n_lanes.eq(self.n_lanes)]

@ResetInserter()
class LiteDSPGrayMapper(_LiteDSPGray):
    """Binary to Gray (``g = b ^ (b >> 1)``) on ``n_lanes`` words of ``width`` bits per beat, so
    adjacent constellation points differ in one bit. Latency 1."""
    def __init__(self, width=2, n_lanes=1, with_csr=True):
        _LiteDSPGray.__init__(self, True, width, n_lanes, with_csr)

@ResetInserter()
class LiteDSPGrayDemapper(_LiteDSPGray):
    """Gray to binary (prefix XOR from the MSB) per lane. Latency 1."""
    def __init__(self, width=2, n_lanes=1, with_csr=True):
        _LiteDSPGray.__init__(self, False, width, n_lanes, with_csr)
