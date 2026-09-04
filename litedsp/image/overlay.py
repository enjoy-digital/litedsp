#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Box overlay: draw rectangle outlines from a host table."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common       import (check, pixel_layout, pixel_fields, add_bypass, add_bypass_csr,
                                  bits_for)
from litedsp.image.common import LiteDSPPixelCounter

# Box Overlay --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPBoxOverlay(LiteXModule):
    """Draw up to ``n_boxes`` rectangle outlines on a pixel stream.

    Each box (``x0``, ``y0``, ``x1``, ``y1`` inclusive corners, colour, enable) lives in a shadow
    table written through ``box_index`` and committed at the next accepted ``first``; the
    runtime ``thickness`` (1..15) sets the outline width and the lowest enabled box wins where
    outlines overlap; ``boxes`` seeds both tables at build time. Coordinates come from a
    :class:`LiteDSPPixelCounter`. ``bypass``;
    latency 1.
    """
    def __init__(self, data_width=8, n_channels=3, n_boxes=4, thickness=1, boxes=None,
                 coord_bits=12, with_csr=True):
        check(1 <= n_boxes <= 16, "expected 1 <= n_boxes <= 16")
        check(1 <= thickness <= 15, "expected 1 <= thickness <= 15")
        boxes = list(boxes or [])
        check(len(boxes) <= n_boxes, "expected at most n_boxes boxes")
        check(all(len(b) == 6 for b in boxes), "expected boxes as (x0, y0, x1, y1, color, enable)")
        self.data_width = data_width
        self.n_channels = n_channels
        self.n_boxes    = n_boxes
        self.coord_bits = coord_bits
        self.latency    = 1
        self.sink   = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        CW = n_channels*data_width
        self.box_index  = Signal(max=max(n_boxes, 2))
        self.box_x0, self.box_y0, self.box_x1, self.box_y1 = [
            Signal(coord_bits, name=n) for n in ("box_x0", "box_y0", "box_x1", "box_y1")]
        self.box_color  = Signal(CW)
        self.box_enable = Signal()
        self.box_we     = Signal()
        self.commit     = Signal()
        self.commit_pending = Signal()
        self.thickness  = Signal(4, reset=thickness)

        # # #

        fields = pixel_fields(n_channels)
        N = n_boxes
        init = {n: [0]*N for n in ("x0", "y0", "x1", "y1", "color", "en")}
        for k, (x0, y0, x1, y1, color, en) in enumerate(boxes):
            packed = int(color) if n_channels == 1 else sum(int(v) << (i*data_width) for i,
                                                            v in enumerate(color))
            init["x0"][k], init["y0"][k], init["x1"][k], init["y1"][k] = int(x0), int(y0), int(
                x1), int(y1)
            init["color"][k], init["en"][k] = packed, int(bool(en))
        def table(name, key, width):
            return [Signal(width, reset=init[key][k], name=f"{name}{k}") for k in range(N)]
        sh = {n: table("sh_" + n, n, coord_bits) for n in ("x0", "y0", "x1", "y1")}
        sh["color"], sh["en"] = table("sh_color", "color", CW), table("sh_en", "en", 1)
        ac = {n: table("ac_" + n, n, coord_bits) for n in ("x0", "y0", "x1", "y1")}
        ac["color"], ac["en"] = table("ac_color", "color", CW), table("ac_en", "en", 1)
        self.sync += If(self.box_we,
            *[If(self.box_index == k,
                sh["x0"][k].eq(self.box_x0), sh["y0"][k].eq(self.box_y0),
                sh["x1"][k].eq(self.box_x1), sh["y1"][k].eq(self.box_y1),
                sh["color"][k].eq(self.box_color), sh["en"][k].eq(self.box_enable),
            ) for k in range(N)],
        )
        adv, xfer = Signal(), Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv),
                      xfer.eq(self.sink.valid & adv)]
        do_commit = Signal()
        self.comb += do_commit.eq(self.commit_pending & xfer & self.sink.first)
        self.sync += [
            If(self.commit, self.commit_pending.eq(1)),
            If(do_commit, *[ac[n][k].eq(sh[n][k]) for n in ac for k in range(N)],
               self.commit_pending.eq(0)),
        ]
        eff = {n: [Mux(do_commit, sh[n][k], ac[n][k]) for k in range(N)] for n in ac}
        self.counter = cnt = LiteDSPPixelCounter(coord_bits)
        self.comb += [cnt.xfer.eq(xfer), cnt.first.eq(self.sink.first), cnt.eol.eq(self.sink.eol),
                      cnt.last.eq(self.sink.last)]
        col, row = Signal((coord_bits + 1, True)), Signal((coord_bits + 1, True))
        self.comb += [col.eq(cnt.col), row.eq(cnt.row)]
        t = Signal((5, True))
        self.comb += t.eq(self.thickness)
        hit, color = Signal(), Signal(CW)
        self.comb += color.eq(0)
        for k in reversed(range(N)):                          # Lowest index wins (last assignment).
            x0, y0, x1, y1 = [Signal((coord_bits + 1, True), name=f"s{n}{k}")
                                      for n in ("x0", "y0", "x1", "y1")]
            self.comb += [x0.eq(eff["x0"][k]), y0.eq(eff["y0"][k]), x1.eq(eff["x1"][k]),
                          y1.eq(eff["y1"][k])]
            inside = Signal()
            edge   = Signal()
            self.comb += [
                inside.eq((col >= x0) & (col <= x1) & (row >= y0) & (row <= y1)),
                edge.eq(
                    inside & ((col - x0 < t) | (x1 - col < t) | (row - y0 < t) | (y1 - row < t))),
                If(eff["en"][k] & edge, hit.eq(1), color.eq(eff["color"][k])),
            ]
        self.sync += If(adv,
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first), self.source.eol.eq(self.sink.eol),
            self.source.last.eq(self.sink.last),
            *[getattr(self.source, f).eq(Mux(hit, color[c*data_width:(c + 1)*data_width],
                                             getattr(self.sink, f))) for c, f in enumerate(fields)],
        )
        add_bypass(self)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        CB, CW = self.coord_bits, self.n_channels*self.data_width
        self._box_index = CSRStorage(len(self.box_index), name="box_index",
                                     description="Shadow box to write.")
        self._box_origin = CSRStorage(fields=[
            CSRField("x0", size=CB, offset=0,  description="Left column."),
            CSRField("y0", size=CB, offset=16, description="Top row."),
        ])
        self._box_corner = CSRStorage(fields=[
            CSRField("x1", size=CB, offset=0,  description="Right column (inclusive)."),
            CSRField("y1", size=CB, offset=16, description="Bottom row (inclusive)."),
        ])
        self._box_color = CSRStorage(fields=[
            CSRField("color",  size=CW, offset=0,  description="Outline colour (channels packed LSB-first)."),
            CSRField("enable", size=1,  offset=31, description="Box enabled."),
        ], description="Writing stores the shadow box at box_index.")
        self._control = CSRStorage(fields=[
            CSRField("commit",    size=1, offset=0, pulse=True, description="Apply the shadow table at the next frame start."),
            CSRField("thickness", size=4, offset=4, reset=self.thickness.reset.value, description="Outline thickness (1..15)."),
        ])
        self._status = CSRStatus(fields=[CSRField("commit_pending", size=1, offset=0, description="A commit waits for the next frame.")])
        self.comb += [
            self.box_index.eq(self._box_index.storage),
            self.box_x0.eq(self._box_origin.fields.x0), self.box_y0.eq(self._box_origin.fields.y0),
            self.box_x1.eq(self._box_corner.fields.x1), self.box_y1.eq(self._box_corner.fields.y1),
            self.box_color.eq(self._box_color.fields.color),
            self.box_enable.eq(self._box_color.fields.enable),
            self.box_we.eq(self._box_color.re),
            self.commit.eq(self._control.fields.commit),
            self.thickness.eq(self._control.fields.thickness),
            self._status.fields.commit_pending.eq(self.commit_pending),
        ]
        add_bypass_csr(self)
