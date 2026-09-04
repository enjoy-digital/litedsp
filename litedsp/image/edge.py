#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Edge detection: Sobel gradient magnitude (and quantised direction)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common           import check, pixel_layout, clamped
from litedsp.image.linebuffer import LiteDSPLineBuffer, BORDERS

SOBEL_L1, SOBEL_LINF, SOBEL_APPROX = 0, 1, 2

# Sobel --------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSobel(LiteXModule):
    """Sobel edge magnitude on a mono raster stream.

    ``gx`` and ``gy`` (adders only) come from a 3x3 :class:`LiteDSPLineBuffer` window; the
    runtime ``mode`` picks the magnitude ``|gx| + |gy|`` (L1), ``max(|gx|, |gy|)`` (L-inf) or
    ``max + min/4`` (alpha-max-beta-min), then ``clamped(rounded(mag, shift))`` (``shift = 3``
    maps the L1 maximum ``8 * full`` onto the code range). With ``with_direction`` a 2-bit
    ``direction`` field (0 horizontal edge, 1 = 45 degrees, 2 vertical, 3 = 135 degrees, quantised
    with tan 22.5 = 53/128) is added. ``bypass`` outputs the window centre. Latency
    ``line_buffer.latency + 3``.
    """
    def __init__(self, data_width=8, width=640, max_width=None, border="replicate", mode="l1",
                 shift=3,
        with_direction=False, with_csr=True):
        check(mode in ("l1", "linf", "approx"), "expected mode in ('l1', 'linf', 'approx')")
        check(0 <= shift <= 7, "expected 0 <= shift <= 7")
        self.data_width = data_width
        self.with_direction = with_direction
        self.lb = LiteDSPLineBuffer(data_width, 1, 3, width, max_width, border, with_csr=False)
        self.latency = self.lb.latency + 3
        self.sink   = self.lb.sink
        layout = pixel_layout(data_width, 1) + ([("direction", 2)] if with_direction else [])
        self.source = stream.Endpoint(layout)
        self.mode   = Signal(2, reset=("l1", "linf", "approx").index(mode))
        self.shift  = Signal(3, reset=shift)
        self.bypass = Signal()
        self.geometry_error = self.lb.geometry_error
        self.clear = self.lb.clear

        # # #

        DW = data_width
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.lb.source.ready.eq(adv)]
        w = [[Signal((DW + 1, True), name=f"w{i}{j}") for j in range(3)] for i in range(3)]
        for i in range(3):
            for j in range(3):
                self.comb += w[i][j].eq(getattr(self.lb.source, f"w{i}{j}"))
        # S1: gradients.
        GW = DW + 4
        gx, gy = Signal((GW, True)), Signal((GW, True))
        v1, f1, e1, l1 = Signal(), Signal(), Signal(), Signal()
        c1 = Signal(DW)
        self.sync += If(adv,
            gx.eq((w[0][2] - w[0][0]) + ((w[1][2] - w[1][0]) << 1) + (w[2][2] - w[2][0])),
            gy.eq((w[2][0] - w[0][0]) + ((w[2][1] - w[0][1]) << 1) + (w[2][2] - w[0][2])),
            v1.eq(self.lb.source.valid), f1.eq(self.lb.source.first), e1.eq(self.lb.source.eol),
            l1.eq(self.lb.source.last),
            c1.eq(self.lb.source.w11),
        )
        # S2: magnitudes and direction.
        ax, ay = Signal(GW), Signal(GW)
        mx, mn = Signal(GW), Signal(GW)
        mag = Signal(GW + 1)
        self.comb += [
            ax.eq(Mux(gx < 0, -gx, gx)), ay.eq(Mux(gy < 0, -gy, gy)),
            mx.eq(Mux(ax > ay, ax, ay)), mn.eq(Mux(ax > ay, ay, ax)),
            mag.eq(Mux(self.mode == SOBEL_L1, ax + ay,
                       Mux(self.mode == SOBEL_LINF, mx, mx + (mn >> 2)))),
        ]
        # Direction: 0 = |gy| dominant (horizontal edge), 2 = |gx| dominant (vertical edge),
        # diagonals when |gx|/|gy| is within tan(22.5..67.5) degrees; the sign of gx*gy separates
        # the two diagonals.
        t = Signal(GW + 7)
        u = Signal(GW + 7)
        diag = Signal()
        self.comb += [
            t.eq(mn << 7), u.eq(mx*53),
            diag.eq(t > u),                                             # mn/mx > tan 22.5.
        ]
        same_sign = Signal()
        self.comb += same_sign.eq((gx < 0) == (gy < 0))
        direction = Signal(2)
        self.comb += direction.eq(Mux(diag, Mux(same_sign, 1, 3), Mux(ax > ay, 2, 0)))
        v2, f2, e2, l2 = Signal(), Signal(), Signal(), Signal()
        c2 = Signal(DW)
        mag2 = Signal(GW + 1)
        dir2 = Signal(2)
        self.sync += If(adv,
            v2.eq(v1), f2.eq(f1), e2.eq(e1), l2.eq(l1), c2.eq(c1), mag2.eq(mag), dir2.eq(direction),
        )
        # S3: rounding, clamp, output.
        r = Signal((GW + 2, True))
        self.comb += r.eq(
            (mag2 + Mux(self.shift == 0, 0, (1 << 6) >> (7 - self.shift))) >> self.shift)
        self.sync += If(adv,
            self.source.valid.eq(v2),
            self.source.first.eq(f2), self.source.eol.eq(e2), self.source.last.eq(l2),
            self.source.data.eq(Mux(self.bypass, c2, clamped(r, DW))),
            *([self.source.direction.eq(dir2)] if with_direction else []),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("mode",   size=2, offset=0, reset=self.mode.reset.value, description="0 L1, 1 L-inf, 2 alpha-max-beta-min."),
            CSRField("shift",  size=3, offset=4, reset=self.shift.reset.value, description="Right shift of the magnitude."),
            CSRField("bypass", size=1, offset=8, description="Pass the window centre (same latency)."),
            CSRField("clear",  size=1, offset=9, pulse=True, description="Clear the geometry error."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("geometry_error", size=1, offset=0, description="Sticky: line length changed or exceeded max_width."),
        ])
        self.comb += [
            self.mode.eq(self._control.fields.mode), self.shift.eq(self._control.fields.shift),
            self.bypass.eq(self._control.fields.bypass), self.clear.eq(self._control.fields.clear),
            self._status.fields.geometry_error.eq(self.geometry_error),
        ]
