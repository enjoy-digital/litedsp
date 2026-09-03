#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Rank-order filtering on 3x3 windows: median, erosion (min), dilation (max)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common           import check, pixel_layout, pixel_fields
from litedsp.image.linebuffer import LiteDSPLineBuffer, BORDERS

# Sorting network: odd-even transposition sort of 9 inputs (9 rounds alternating the even and
# odd neighbour pairs, 36 compare-exchanges, provably sorting); registered every three rounds.
SORT9 = [[(0, 1), (2, 3), (4, 5), (6, 7)] if r % 2 == 0 else [(1, 2), (3, 4), (5, 6), (7, 8)] for r in range(9)]
_REG_AFTER = {2, 5, 8}                                                  # Register stages.

# Rank Filter --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPRankFilter(LiteXModule):
    """Rank-order filter on a 3x3 neighbourhood (per channel).

    A 36-comparator odd-even transposition network (three pipeline registers) orders the nine
    window pixels;
    the runtime ``rank`` (0 = erosion / minimum, 4 = median, 8 = dilation / maximum) selects the
    output. ``bypass`` outputs the window centre. Latency ``line_buffer.latency + 4``.
    """
    def __init__(self, data_width=8, n_channels=1, rank=4, width=640, max_width=None, border="replicate",
        with_csr=True):
        check(0 <= rank <= 8, "expected 0 <= rank <= 8")
        self.data_width = data_width
        self.n_channels = n_channels
        self.lb = LiteDSPLineBuffer(data_width, n_channels, 3, width, max_width, border, with_csr=False)
        self.latency = self.lb.latency + 4
        self.sink   = self.lb.sink
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.rank   = Signal(4, reset=rank)
        self.bypass = Signal()
        self.geometry_error = self.lb.geometry_error
        self.clear = self.lb.clear

        # # #

        DW = data_width
        fields = pixel_fields(n_channels)
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.lb.source.ready.eq(adv)]
        n_regs = len(_REG_AFTER)                                        # Tag stages before the output register.
        tags = [(Signal(name=f"v{k}"), Signal(name=f"f{k}"), Signal(name=f"e{k}"), Signal(name=f"l{k}")) for k in range(n_regs)]
        centres = [[Signal(DW, name=f"c{k}_{c}") for c in range(n_channels)] for k in range(n_regs)]
        src = (self.lb.source.valid, self.lb.source.first, self.lb.source.eol, self.lb.source.last)
        self.sync += If(adv, *[t.eq(s) for t, s in zip(tags[0], src)],
                        *[centres[0][c].eq(self.lb.source.w11[c*DW:(c + 1)*DW]) for c in range(n_channels)])
        for k in range(1, n_regs):
            self.sync += If(adv, *[t.eq(s) for t, s in zip(tags[k], tags[k - 1])],
                            *[centres[k][c].eq(centres[k - 1][c]) for c in range(n_channels)])
        sorted_out = []
        for c in range(n_channels):
            vals = [Signal(DW, name=f"s{c}_{k}") for k in range(9)]
            for k in range(9):
                i, j = divmod(k, 3)
                self.comb += vals[k].eq(getattr(self.lb.source, f"w{i}{j}")[c*DW:(c + 1)*DW])
            for stage, pairs in enumerate(SORT9):
                new = list(vals)
                for a, b in pairs:
                    lo, hi = Signal(DW, name=f"lo{c}_{stage}_{a}"), Signal(DW, name=f"hi{c}_{stage}_{b}")
                    self.comb += [lo.eq(Mux(vals[a] < vals[b], vals[a], vals[b])), hi.eq(Mux(vals[a] < vals[b], vals[b], vals[a]))]
                    new[a], new[b] = lo, hi
                if stage in _REG_AFTER:
                    regs = [Signal(DW, name=f"r{c}_{stage}_{k}") for k in range(9)]
                    self.sync += If(adv, *[r.eq(n) for r, n in zip(regs, new)])
                    new = regs
                vals = new
            sorted_out.append(vals)
        vN, fN, eN, lN = tags[-1]
        self.sync += If(adv,
            self.source.valid.eq(vN), self.source.first.eq(fN), self.source.eol.eq(eN), self.source.last.eq(lN),
            *[getattr(self.source, f).eq(Mux(self.bypass, centres[-1][c], Array(sorted_out[c])[self.rank])) for c, f in enumerate(fields)],
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("rank",   size=4, offset=0, reset=self.rank.reset.value, description="0 erode (min), 4 median, 8 dilate (max)."),
            CSRField("bypass", size=1, offset=4, description="Pass the window centre (same latency)."),
            CSRField("clear",  size=1, offset=5, pulse=True, description="Clear the geometry error."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("geometry_error", size=1, offset=0, description="Sticky: line length changed or exceeded max_width."),
        ])
        self.comb += [
            self.rank.eq(self._control.fields.rank), self.bypass.eq(self._control.fields.bypass),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.geometry_error.eq(self.geometry_error),
        ]
