#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Geometry: box downscaling and region-of-interest cropping."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common       import check, pixel_layout, pixel_fields, bits_for
from litedsp.image.common import LiteDSPPixelCounter

# Downscaler ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDownscaler(LiteXModule):
    """Exact box-mean downscaling by ``decimation`` (2, 4 or 8) in both directions.

    Pixels accumulate horizontally over ``decimation`` columns, the partial sums accumulate
    vertically in a RAM indexed by the tile column (``max_width / decimation`` deep), and each
    tile emits ``rounded(sum, 2 log2 D)`` on its last row and column. Partial tiles at the right
    and bottom edges are dropped; the output is framed from the tile counters and the runtime
    ``width`` / ``height`` (``eol`` at the last full tile column, ``last`` on the last full tile
    row). Rate changer (one output per ``D^2`` inputs); latency 2 from the tile's last pixel.
    """
    def __init__(self, data_width=8, n_channels=1, decimation=2, width=640, height=480,
                 max_width=None,
        coord_bits=12, with_csr=True):
        check(decimation in (2, 4, 8), "expected decimation in (2, 4, 8)")
        if max_width is None:
            max_width = width
        check(decimation <= width <= max_width and height >= decimation,
              "expected decimation <= width <= max_width, height >= decimation")
        self.data_width = data_width
        self.n_channels = n_channels
        self.decimation = decimation
        self.max_width  = max_width
        self.coord_bits = coord_bits
        self.latency    = 2
        self.sink   = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.width  = Signal(coord_bits, reset=width)
        self.height = Signal(coord_bits, reset=height)

        # # #

        D, DW = decimation, data_width
        L  = bits_for(D - 1)                                            # log2 D.
        SW = DW + 2*L
        fields = pixel_fields(n_channels)
        adv, xfer = Signal(), Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv),
                      xfer.eq(self.sink.valid & adv)]
        self.counter = cnt = LiteDSPPixelCounter(coord_bits)
        self.comb += [cnt.xfer.eq(xfer), cnt.first.eq(self.sink.first), cnt.eol.eq(self.sink.eol),
                      cnt.last.eq(self.sink.last)]
        tiles_x, tiles_y = Signal(coord_bits), Signal(coord_bits)     # Full tiles per frame.
        self.comb += [tiles_x.eq(self.width >> L), tiles_y.eq(self.height >> L)]
        tx, ty = Signal(coord_bits), Signal(coord_bits)             # Tile coordinates of the pixel.
        px, py = Signal(L), Signal(L)                                   # Position inside the tile.
        self.comb += [tx.eq(cnt.col >> L), ty.eq(cnt.row >> L), px.eq(cnt.col[:L]),
                      py.eq(cnt.row[:L])]
        in_tile = Signal()
        self.comb += in_tile.eq((tx < tiles_x) & (ty < tiles_y))
        # Horizontal accumulator per channel (D pixels), vertical RAM per tile column.
        hacc = [Signal(SW, name=f"hacc{c}") for c in range(n_channels)]
        n_tiles = max_width//D
        self.specials.mem = mem = Memory(n_channels*SW, n_tiles)
        rp = mem.get_port(has_re=True)
        wp = mem.get_port(write_capable=True)
        self.specials += rp, wp
        self.comb += [rp.adr.eq(tx[:bits_for(n_tiles - 1)]), rp.re.eq(adv)]
        # S1: the pixel's contribution folded into the tile sum.
        v1, tile_end1 = Signal(), Signal()
        tx1, ty1 = Signal(coord_bits), Signal(coord_bits)
        px1, py1 = Signal(L), Signal(L)
        x1 = [Signal(DW, name=f"x1_{c}") for c in range(n_channels)]
        in_tile1 = Signal()
        self.sync += If(adv,
            v1.eq(xfer), tx1.eq(tx), ty1.eq(ty), px1.eq(px), py1.eq(py), in_tile1.eq(in_tile),
            *[x1[c].eq(getattr(self.sink, f)) for c, f in enumerate(fields)],
        )
        # Row sums: hacc restarts at px == 0; the tile sum in RAM restarts at py == 0.
        vsum  = [Signal(SW, name=f"vsum{c}") for c in range(n_channels)]
        hnext = [Signal(SW, name=f"hnext{c}") for c in range(n_channels)]
        total = [Signal(SW, name=f"total{c}") for c in range(n_channels)]
        for c in range(n_channels):
            self.comb += [
                hnext[c].eq(Mux(px1 == 0, 0, hacc[c]) + x1[c]),
                vsum[c].eq(Mux(py1 == 0, 0, rp.dat_r[c*SW:(c + 1)*SW])),
                total[c].eq(vsum[c] + hnext[c]),
            ]
        row_end = Signal()
        self.comb += row_end.eq(px1 == D - 1)
        self.sync += If(adv & v1, *[hacc[c].eq(hnext[c]) for c in range(n_channels)])
        self.comb += [
            wp.adr.eq(tx1[:bits_for(n_tiles - 1)]), wp.dat_w.eq(Cat(*total)),
            wp.we.eq(adv & v1 & row_end & in_tile1),
        ]
        emit = Signal()
        self.comb += emit.eq(v1 & row_end & (py1 == D - 1) & in_tile1)
        self.sync += If(adv,
            self.source.valid.eq(emit),
            *[getattr(self.source, f).eq((total[c] + (1 << (2*L - 1))) >> (2*L)) for c,
              f in enumerate(fields)],
            self.source.first.eq((tx1 == 0) & (ty1 == 0)),
            self.source.eol.eq(tx1 == tiles_x - 1),
            self.source.last.eq((tx1 == tiles_x - 1) & (ty1 == tiles_y - 1)),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        CB = self.coord_bits
        self._geometry = CSRStorage(fields=[
            CSRField("width",  size=CB, offset=0,  reset=self.width.reset.value,  description="Input pixels per line."),
            CSRField("height", size=CB, offset=16, reset=self.height.reset.value, description="Input lines per frame."),
        ])
        self.comb += [self.width.eq(self._geometry.fields.width),
                      self.height.eq(self._geometry.fields.height)]

# Crop ---------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCrop(LiteXModule):
    """Pass a rectangular region of interest, consume everything else.

    The ROI (``x0``, ``y0``, ``roi_width``, ``roi_height``) is shadowed and committed at the next
    accepted ``first``; the output is re-framed (``first`` / ``eol`` / ``last`` from the ROI
    corners). A ROI that extends beyond the learned frame sets the sticky ``geometry_error``.
    Rate changer; latency 1.
    """
    def __init__(self, data_width=8, n_channels=3, x0=0, y0=0, roi_width=640, roi_height=480,
                 coord_bits=12,
        with_csr=True):
        check(roi_width >= 1 and roi_height >= 1, "expected roi_width, roi_height >= 1")
        check(x0 + roi_width < 2**coord_bits and y0 + roi_height < 2**coord_bits,
              "expected the ROI inside the coordinate range")
        self.data_width = data_width
        self.n_channels = n_channels
        self.coord_bits = coord_bits
        self.latency    = 1
        self.sink   = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.x0, self.y0 = Signal(coord_bits, reset=x0), Signal(coord_bits, reset=y0)
        self.roi_width, self.roi_height = Signal(coord_bits, reset=roi_width), Signal(coord_bits,
            reset=roi_height)
        self.commit = Signal()
        self.commit_pending = Signal()
        self.geometry_error = Signal()
        self.clear = Signal()

        # # #

        fields = pixel_fields(n_channels)
        adv, xfer = Signal(), Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv),
                      xfer.eq(self.sink.valid & adv)]
        self.counter = cnt = LiteDSPPixelCounter(coord_bits)
        self.comb += [cnt.xfer.eq(xfer), cnt.first.eq(self.sink.first), cnt.eol.eq(self.sink.eol),
                      cnt.last.eq(self.sink.last)]
        # Active ROI.
        ax0, ay0, aw, ah = [Signal(coord_bits, name=n) for n in ("ax0", "ay0", "aw", "ah")]
        do_commit = Signal()
        self.comb += do_commit.eq(xfer & self.sink.first & self.commit_pending)
        self.sync += [
            If(self.commit, self.commit_pending.eq(1)),
            If(do_commit,
                ax0.eq(self.x0), ay0.eq(self.y0), aw.eq(self.roi_width), ah.eq(self.roi_height),
                self.commit_pending.eq(0),
            ),
        ]
        for a, v in ((ax0, self.x0), (ay0, self.y0), (aw, self.roi_width), (ah, self.roi_height)):
            a.reset = v.reset
        # The committing beat (the frame's first pixel) already uses the new ROI.
        ex0, ey0, ew, eh = [Signal(coord_bits, name=n) for n in ("ex0", "ey0", "ew", "eh")]
        self.comb += [
            ex0.eq(Mux(do_commit, self.x0, ax0)), ey0.eq(Mux(do_commit, self.y0, ay0)),
            ew.eq(Mux(do_commit, self.roi_width, aw)), eh.eq(Mux(do_commit, self.roi_height, ah)),
        ]
        x1, y1 = Signal((coord_bits + 1, True)), Signal((coord_bits + 1, True))
        self.comb += [x1.eq(cnt.col - ex0), y1.eq(cnt.row - ey0)]
        inside = Signal()
        self.comb += inside.eq((x1 >= 0) & (x1 < ew) & (y1 >= 0) & (y1 < eh))
        self.sync += [
            If(adv,
                self.source.valid.eq(xfer & inside),
                *[getattr(self.source, f).eq(getattr(self.sink, f)) for f in fields],
                self.source.first.eq((x1 == 0) & (y1 == 0)),
                self.source.eol.eq(x1 == ew - 1),
                self.source.last.eq((x1 == ew - 1) & (y1 == eh - 1)),
            ),
            # The ROI must fit the learned frame (checked at the frame's end).
            If(xfer & self.sink.last & ((ax0 + aw > cnt.col + 1) | (ay0 + ah > cnt.row + 1)),
                self.geometry_error.eq(1),
            ),
            If(self.clear, self.geometry_error.eq(0)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        CB = self.coord_bits
        self._origin = CSRStorage(fields=[
            CSRField("x0", size=CB, offset=0,  reset=self.x0.reset.value, description="ROI left column."),
            CSRField("y0", size=CB, offset=16, reset=self.y0.reset.value, description="ROI top row."),
        ])
        self._size = CSRStorage(fields=[
            CSRField("width",  size=CB, offset=0,  reset=self.roi_width.reset.value,  description="ROI width."),
            CSRField("height", size=CB, offset=16, reset=self.roi_height.reset.value, description="ROI height."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("commit", size=1, offset=0, pulse=True, description="Apply the ROI at the next frame start."),
            CSRField("clear",  size=1, offset=1, pulse=True, description="Clear the geometry error."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("commit_pending", size=1, offset=0, description="A ROI change waits for the next frame."),
            CSRField("geometry_error", size=1, offset=1, description="Sticky: the ROI exceeded the frame."),
        ])
        self.comb += [
            self.x0.eq(self._origin.fields.x0), self.y0.eq(self._origin.fields.y0),
            self.roi_width.eq(self._size.fields.width),
            self.roi_height.eq(self._size.fields.height),
            self.commit.eq(self._control.fields.commit), self.clear.eq(self._control.fields.clear),
            self._status.fields.commit_pending.eq(self.commit_pending),
            self._status.fields.geometry_error.eq(self.geometry_error),
        ]
