#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Bilinear Bayer demosaic."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common           import check, pixel_layout, bits_for
from litedsp.image.linebuffer import LiteDSPLineBuffer, BORDERS
from litedsp.image.common     import LiteDSPPixelCounter
from litedsp.image.design     import bayer_phase, BAYER_PATTERNS

# Debayer ------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDebayer(LiteXModule):
    """Bilinear demosaic of a raw Bayer (mono) stream into RGB.

    A 3x3 :class:`LiteDSPLineBuffer` (``mirror`` border by default, which keeps the colour phase
    of the virtual pixels) feeds the interpolation; the colour site follows the output
    coordinate parity (a :class:`LiteDSPPixelCounter` on the window stream) XOR the runtime
    2-bit ``phase`` (row, column) for cropped sensors, starting from the build-time ``pattern``.
    Red / blue sites take the centre, the mean of the four edge neighbours and of the four
    corners; green sites take the centre and the two-pixel means along and across the row
    (rounded half up). Latency ``line_buffer.latency + 2``.
    """
    def __init__(self, data_width=8, pattern="rggb", width=640, max_width=None, border="mirror",
                 with_csr=True):
        check(pattern in BAYER_PATTERNS, f"expected pattern in {BAYER_PATTERNS}")
        self.data_width = data_width
        self.pattern    = pattern
        self.lb = LiteDSPLineBuffer(data_width, 1, 3, width, max_width, border, with_csr=False)
        self.latency = self.lb.latency + 2
        self.sink   = self.lb.sink
        self.source = stream.Endpoint(pixel_layout(data_width, 3))
        self.phase  = Signal(2)                                         # (row, col) parity flip.
        self.geometry_error = self.lb.geometry_error
        self.clear = self.lb.clear

        # # #

        DW = data_width
        adv, xfer = Signal(), Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.lb.source.ready.eq(adv),
                      xfer.eq(self.lb.source.valid & adv)]
        self.counter = cnt = LiteDSPPixelCounter(coord_bits=max(4, bits_for(self.lb.max_width) + 1))
        self.comb += [cnt.xfer.eq(xfer), cnt.first.eq(self.lb.source.first),
                      cnt.eol.eq(self.lb.source.eol), cnt.last.eq(self.lb.source.last)]
        w = [[getattr(self.lb.source, f"w{i}{j}") for j in range(3)] for i in range(3)]
        ph = bayer_phase(pattern)                              # Colour at (row parity, col parity).
        rp, cp = Signal(), Signal()
        self.comb += [rp.eq(cnt.row[0] ^ self.phase[1]), cp.eq(cnt.col[0] ^ self.phase[0])]
        site = Signal(2)                                                # 0 R, 1 G, 2 B.
        self.comb += site.eq(Array([C(v, 2) for v in ph])[Cat(cp, rp)])
        # Whether a green site sits on a red row (red left/right) or a blue row.
        green_red_row = Signal()
        self.comb += green_red_row.eq(
            Array([C(int(ph[2*r] == 0 or ph[2*r + 1] == 0), 1) for r in range(2)])[rp])
        # S1: sums.
        edge4, corner4 = Signal(DW + 2), Signal(DW + 2)
        horiz2, vert2  = Signal(DW + 1), Signal(DW + 1)
        centre1 = Signal(DW)
        site1, grr1 = Signal(2), Signal()
        v1, f1, e1, l1 = Signal(), Signal(), Signal(), Signal()
        self.sync += If(adv,
            edge4.eq(w[0][1] + w[1][0] + w[1][2] + w[2][1]),
            corner4.eq(w[0][0] + w[0][2] + w[2][0] + w[2][2]),
            horiz2.eq(w[1][0] + w[1][2]), vert2.eq(w[0][1] + w[2][1]),
            centre1.eq(w[1][1]), site1.eq(site), grr1.eq(green_red_row),
            v1.eq(self.lb.source.valid), f1.eq(self.lb.source.first), e1.eq(self.lb.source.eol),
            l1.eq(self.lb.source.last),
        )
        m4e, m4c = Signal(DW), Signal(DW)
        m2h, m2v = Signal(DW), Signal(DW)
        self.comb += [
            m4e.eq((edge4 + 2) >> 2), m4c.eq((corner4 + 2) >> 2),
            m2h.eq((horiz2 + 1) >> 1), m2v.eq((vert2 + 1) >> 1),
        ]
        r, g, b = Signal(DW), Signal(DW), Signal(DW)
        self.comb += [
            If(site1 == 0,                                              # Red site.
                r.eq(centre1), g.eq(m4e), b.eq(m4c),
            ).Elif(site1 == 2,                                          # Blue site.
                b.eq(centre1), g.eq(m4e), r.eq(m4c),
            ).Else(                                                     # Green site.
                g.eq(centre1),
                If(grr1, r.eq(m2h), b.eq(m2v)).Else(r.eq(m2v), b.eq(m2h)),
            ),
        ]
        self.sync += If(adv,
            self.source.valid.eq(v1), self.source.first.eq(f1), self.source.eol.eq(e1),
            self.source.last.eq(l1),
            self.source.r.eq(r), self.source.g.eq(g), self.source.b.eq(b),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("phase", size=2, offset=0, description="Flip the (col, row) colour phase (cropped sensors)."),
            CSRField("clear", size=1, offset=4, pulse=True, description="Clear the geometry error."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("geometry_error", size=1, offset=0, description="Sticky: line length changed or exceeded max_width."),
        ])
        self.comb += [
            self.phase.eq(self._control.fields.phase), self.clear.eq(self._control.fields.clear),
            self._status.fields.geometry_error.eq(self.geometry_error),
        ]
