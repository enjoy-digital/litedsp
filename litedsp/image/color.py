#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Colour space conversion: a 3x3 (or 1x3) matrix with input / output offsets."""

from functools import reduce
from operator  import add

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common       import check, pixel_layout, clamped, rounded, add_bypass, add_bypass_csr
from litedsp.image.design import color_preset

# Color Matrix -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPColorMatrix(LiteXModule):
    """``y_c = clamped(rounded(sum_k m[c][k] * (x_k - in_off_k), coeff_frac) + out_off_c)`` on RGB
    pixels, three or one output channel.

    Coefficients are signed Q(coeff_width - coeff_frac).coeff_frac (presets in
    ``litedsp.image.design.color_preset``: BT.601 / 709 studio, JPEG full range, grey, selects),
    offsets in codes. The nine coefficients and six offsets live in a shadow table
    (``coeff_index`` 0..8 coefficients row-major, 9..11 input offsets, 12..14 output offsets)
    committed at the next accepted ``first`` or immediately. Sticky ``sat``; ``bypass`` when
    ``n_out == 3``. Latency 3.
    """
    def __init__(self, data_width=8, n_out=3, coefficients=None, in_offsets=(0, 0, 0),
                 out_offsets=(0, 0, 0),
        coeff_width=16, coeff_frac=12, with_csr=True):
        check(n_out in (1, 3), "expected n_out in (1, 3)")
        check(0 < coeff_frac < coeff_width <= 18, "expected 0 < coeff_frac < coeff_width <= 18")
        if coefficients is None:
            coefficients = color_preset("identity", data_width, coeff_frac)[
                0] if n_out == 3 else color_preset("rgb_to_gray_601", data_width, coeff_frac)[0]
        check(len(coefficients) == 3*n_out, f"expected {3*n_out} coefficients")
        lim = 1 << (coeff_width - 1)
        check(all(-lim <= int(c) < lim for c in coefficients), "coefficient out of range")
        out_offsets = tuple(out_offsets)[:n_out]
        check(len(out_offsets) == n_out and len(in_offsets) == 3,
              "expected 3 input offsets and n_out output offsets")
        self.data_width  = data_width
        self.n_out       = n_out
        self.coeff_width = coeff_width
        self.coeff_frac  = coeff_frac
        self.latency     = 3
        self.sink   = stream.Endpoint(pixel_layout(data_width, 3))
        self.source = stream.Endpoint(pixel_layout(data_width, n_out))
        self.coeff_index  = Signal(4)
        self.coeff_value  = Signal((coeff_width, True))
        self.coeff_we     = Signal()
        self.commit       = Signal()
        self.commit_now   = Signal()
        self.commit_pending = Signal()
        self.sat = Signal()
        self.clear_sat = Signal()

        # # #

        DW, CW, CF = data_width, coeff_width, coeff_frac
        N = 3*n_out
        OFW = DW + 1
        values = [int(c) for c in coefficients] + [int(v) for v in in_offsets] + [int(v)
            for v in out_offsets]
        widths = [CW]*N + [OFW]*3 + [OFW]*n_out
        active = [Signal((w, True), reset=v, name=f"act{k}") for k,
                  (w, v) in enumerate(zip(widths, values))]
        shadow = [Signal((w, True), reset=v, name=f"sh{k}") for k,
                  (w, v) in enumerate(zip(widths, values))]
        # Shadow index map: 0..N-1 coefficients, 9..11 input offsets, 12..(12+n_out-1) output
        # offsets.
        idx_of = list(range(N)) + [9, 10, 11] + [12 + k for k in range(n_out)]
        self.sync += [
            If(self.coeff_we,
                *[If(self.coeff_index == idx_of[k], shadow[k].eq(self.coeff_value[:widths[k]]))
                    for k in range(len(shadow))],
                self.coeff_index.eq(self.coeff_index + 1),
            ),
        ]
        adv, xfer = Signal(), Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]
        do_commit = Signal()
        self.comb += do_commit.eq(self.commit_now | (self.commit_pending & xfer & self.sink.first))
        self.sync += [
            If(self.commit, self.commit_pending.eq(1)),
            If(do_commit, *[a.eq(s) for a, s in zip(active, shadow)], self.commit_pending.eq(0)),
        ]
        eff = [Signal((w, True), name=f"eff{k}") for k, w in enumerate(widths)]
        self.comb += [eff[k].eq(Mux(do_commit, shadow[k], active[k])) for k in range(len(eff))]
        coef, in_off, out_off = eff[:N], eff[N:N + 3], eff[N + 3:]
        # S1: centred inputs (registered); S2: products (registered); S3: sums, round, offset,
        # clamp.
        x1 = [Signal((DW + 2, True), name=f"x1_{k}") for k in range(3)]
        v1, f1, e1, l1 = Signal(), Signal(), Signal(), Signal()
        c1 = [Signal((CW, True), name=f"c1_{k}") for k in range(N)]
        o1 = [Signal((OFW, True), name=f"o1_{k}") for k in range(n_out)]
        raw1 = [Signal(DW, name=f"raw1_{k}") for k in range(3)]
        self.sync += If(adv,
            v1.eq(self.sink.valid), f1.eq(self.sink.first), e1.eq(self.sink.eol),
            l1.eq(self.sink.last),
            *[x1[k].eq(getattr(self.sink, f) - in_off[k]) for k, f in enumerate(("r", "g", "b"))],
            *[raw1[k].eq(getattr(self.sink, f)) for k, f in enumerate(("r", "g", "b"))],
            *[c1[k].eq(coef[k]) for k in range(N)], *[o1[k].eq(out_off[k]) for k in range(n_out)],
        )
        prods = [Signal((DW + 2 + CW, True), name=f"p{k}") for k in range(N)]
        v2, f2, e2, l2 = Signal(), Signal(), Signal(), Signal()
        o2 = [Signal((OFW, True), name=f"o2_{k}") for k in range(n_out)]
        raw2 = [Signal(DW, name=f"raw2_{k}") for k in range(3)]
        self.sync += If(adv,
            v2.eq(v1), f2.eq(f1), e2.eq(e1), l2.eq(l1),
            *[prods[c*3 + k].eq(x1[k]*c1[c*3 + k]) for c in range(n_out) for k in range(3)],
            *[o2[k].eq(o1[k]) for k in range(n_out)], *[raw2[k].eq(raw1[k]) for k in range(3)],
        )
        acc = [Signal((DW + 2 + CW + 2, True), name=f"acc{c}") for c in range(n_out)]
        ys  = [Signal((DW + 4 + CW - CF + 2, True), name=f"y{c}") for c in range(n_out)]
        self.comb += [acc[c].eq(reduce(add, prods[c*3:c*3 + 3])) for c in range(n_out)]
        self.comb += [ys[c].eq(rounded(acc[c], CF) + o2[c]) for c in range(n_out)]
        ovf = Signal()
        self.comb += ovf.eq(reduce(lambda a, b: a | b, [(y < 0) | (y > (1 << DW) - 1) for y in ys]))
        out_fields = ["data"] if n_out == 1 else ["r", "g", "b"]
        self.sync += [
            If(adv,
                self.source.valid.eq(v2), self.source.first.eq(f2), self.source.eol.eq(e2),
                self.source.last.eq(l2),
                *[getattr(self.source, f).eq(clamped(ys[c], DW)) for c, f in enumerate(out_fields)],
            ),
            If(self.clear_sat, self.sat.eq(0)).Elif(adv & v2 & ovf, self.sat.eq(1)),
        ]
        if n_out == 3:
            add_bypass(self)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        CW = self.coeff_width
        self._coeff_index = CSRStorage(4, name="coeff_index",
                                       description="Shadow index (0..8 matrix, 9..11 input "
                                                   "offsets, 12..14 output offsets); "
                                                   "auto-increments on a value write.")
        self._coeff_value = CSRStorage(CW, name="coeff_value",
                                       description="Writing stores the shadow entry at coeff_index "
                                                   "(signed).")
        self._control = CSRStorage(fields=[
            CSRField("commit",     size=1, offset=0, pulse=True, description="Copy the shadow set at the next frame start."),
            CSRField("commit_now", size=1, offset=1, pulse=True, description="Copy the shadow set immediately."),
            CSRField("clear_sat",  size=1, offset=2, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("commit_pending", size=1, offset=0, description="A commit waits for the next frame start."),
            CSRField("sat",            size=1, offset=1, description="Sticky: an output clamped."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_out",      size=2, offset=0, description="Output channels."),
            CSRField("coeff_frac", size=5, offset=8, description="Coefficient fractional bits."),
        ])
        self.sync += If(self._coeff_index.re, self.coeff_index.eq(self._coeff_index.storage))
        self.comb += [
            self.coeff_value.eq(self._coeff_value.storage), self.coeff_we.eq(self._coeff_value.re),
            self.commit.eq(self._control.fields.commit),
            self.commit_now.eq(self._control.fields.commit_now),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.commit_pending.eq(self.commit_pending),
            self._status.fields.sat.eq(self.sat),
            self._config.fields.n_out.eq(self.n_out),
            self._config.fields.coeff_frac.eq(self.coeff_frac),
        ]
        if self.n_out == 3:
            add_bypass_csr(self)
