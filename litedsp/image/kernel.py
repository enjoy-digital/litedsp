#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""2-D convolution kernel over a line-buffered window."""

from functools import reduce
from operator  import add

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common           import check, pixel_layout, pixel_fields, clamped, rounded, bits_for
from litedsp.image.linebuffer import LiteDSPLineBuffer, BORDERS
from litedsp.image.design     import kernel_preset

# Kernel 2D ----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPKernel2D(LiteXModule):
    """``kernel_size x kernel_size`` correlation kernel on a raster stream (per channel).

    A :class:`LiteDSPLineBuffer` supplies the neighbourhood; each channel computes
    ``sum(coef[i][j] * w[i][j])`` with signed ``coeff_width`` coefficients (row-major, ``coef[0][0]``
    on the top-left neighbour), then ``y = clamped(rounded(acc, shift) + offset)`` with the sticky
    ``sat`` flag. Coefficients live in shadow registers loaded through ``coeff_index`` (auto-
    incremented by a ``coeff_we`` write) and copied to the active set by ``commit`` at the next
    accepted ``first`` (frame-atomic, ``commit_pending`` meanwhile) or immediately by
    ``commit_now``; ``shift`` (0..15) and the signed ``offset`` are runtime. ``bypass`` outputs the
    window centre at the same latency. Presets from ``litedsp.image.design.kernel_preset``.
    ``latency = line_buffer.latency + 2``.
    """
    def __init__(self, data_width=8, n_channels=1, kernel_size=3, coefficients=None, coeff_width=10, shift=0,
        offset=0, width=640, max_width=None, border="replicate", with_csr=True):
        check(kernel_size in (3, 5, 7), "expected kernel_size in (3, 5, 7)")
        check(2 <= coeff_width <= 16, "expected 2 <= coeff_width <= 16")
        check(0 <= shift <= 15, "expected 0 <= shift <= 15")
        K  = kernel_size
        if coefficients is None:
            coefficients = kernel_preset("identity")[0] if K == 3 else [0]*(K*K)
            if K != 3:
                coefficients[(K*K)//2] = 1
        check(len(coefficients) == K*K, f"expected {K*K} coefficients")
        lim = 1 << (coeff_width - 1)
        check(all(-lim <= int(c) < lim for c in coefficients), "coefficient out of range")
        check(-(1 << data_width) <= offset < (1 << data_width), "offset out of range")
        self.data_width   = data_width
        self.n_channels   = n_channels
        self.kernel_size  = kernel_size
        self.coeff_width  = coeff_width
        self.coefficients = [int(c) for c in coefficients]
        self.lb = LiteDSPLineBuffer(data_width, n_channels, K, width, max_width, border, with_csr=False)
        self.latency = self.lb.latency + 2
        self.sink   = self.lb.sink
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.coeff_index  = Signal(max=K*K)
        self.coeff_value  = Signal((coeff_width, True))
        self.coeff_we     = Signal()
        self.commit       = Signal()
        self.commit_now   = Signal()
        self.commit_pending = Signal()
        self.shift  = Signal(4, reset=shift)
        self.offset = Signal((data_width + 1, True), reset=offset)
        self.bypass = Signal()
        self.sat    = Signal()
        self.clear_sat = Signal()
        self.geometry_error = self.lb.geometry_error
        self.clear = self.lb.clear

        # # #

        N, DW, CW = K*K, data_width, coeff_width
        fields = pixel_fields(n_channels)
        active = [Signal((CW, True), reset=self.coefficients[k], name=f"coef{k}") for k in range(N)]
        shadow = [Signal((CW, True), reset=self.coefficients[k], name=f"shadow{k}") for k in range(N)]
        self.sync += [
            If(self.coeff_we,
                *[If(self.coeff_index == k, shadow[k].eq(self.coeff_value)) for k in range(N)],
                If(self.coeff_index == N - 1, self.coeff_index.eq(0)).Else(self.coeff_index.eq(self.coeff_index + 1)),
            ),
        ]
        adv, xfer = Signal(), Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.lb.source.ready.eq(adv),
            xfer.eq(self.lb.source.valid & adv),
        ]
        # Commit: at the next accepted 'first' (frame-atomic) or now.
        do_commit = Signal()
        self.comb += do_commit.eq(self.commit_now | (self.commit_pending & xfer & self.lb.source.first))
        self.sync += [
            If(self.commit, self.commit_pending.eq(1)),
            If(do_commit,
                *[active[k].eq(shadow[k]) for k in range(N)],
                self.commit_pending.eq(0),
            ),
        ]
        # S1: products per channel and tap (registered); S2: sum, round, offset, clamp.
        AW = DW + 1 + CW + bits_for(N)
        prods = [[Signal((DW + 1 + CW, True), name=f"p{c}_{k}") for k in range(N)] for c in range(n_channels)]
        v1, first1, eol1, last1 = Signal(), Signal(), Signal(), Signal()
        centre1 = [Signal(DW, name=f"centre1_{c}") for c in range(n_channels)]
        wsig = [[getattr(self.lb.source, f"w{i}{j}") for j in range(K)] for i in range(K)]
        px = {}
        for c in range(n_channels):
            for k in range(N):
                i, j = divmod(k, K)
                x = Signal((DW + 1, True), name=f"x{c}_{k}")
                self.comb += x.eq(wsig[i][j][c*DW:(c + 1)*DW])
                px[c, k] = x
        # The committing beat already multiplies with the new set (the copy lands on the same edge).
        coef = [Signal((CW, True), name=f"coef_eff{k}") for k in range(N)]
        self.comb += [coef[k].eq(Mux(do_commit, shadow[k], active[k])) for k in range(N)]
        self.sync += If(adv,
            v1.eq(self.lb.source.valid), first1.eq(self.lb.source.first), eol1.eq(self.lb.source.eol), last1.eq(self.lb.source.last),
            *[prods[c][k].eq(px[c, k]*coef[k]) for c in range(n_channels) for k in range(N)],
            *[centre1[c].eq(wsig[K//2][K//2][c*DW:(c + 1)*DW]) for c in range(n_channels)],
        )
        acc = [Signal((AW, True), name=f"acc{c}") for c in range(n_channels)]
        r   = [Signal((AW, True), name=f"r{c}") for c in range(n_channels)]
        y   = [Signal((AW + 1, True), name=f"y{c}") for c in range(n_channels)]
        ovf = Signal()
        self.comb += [acc[c].eq(reduce(add, prods[c])) for c in range(n_channels)]
        self.comb += [r[c].eq((acc[c] + Mux(self.shift == 0, 0, (1 << 15) >> (16 - self.shift))) >> self.shift) for c in range(n_channels)]
        self.comb += [y[c].eq(r[c] + self.offset) for c in range(n_channels)]
        self.comb += ovf.eq(reduce(lambda a, b: a | b, [(y[c] < 0) | (y[c] > (1 << DW) - 1) for c in range(n_channels)]))
        self.sync += [
            If(adv,
                self.source.valid.eq(v1),
                self.source.first.eq(first1), self.source.eol.eq(eol1), self.source.last.eq(last1),
                *[getattr(self.source, f).eq(Mux(self.bypass, centre1[c], clamped(y[c], DW))) for c, f in enumerate(fields)],
            ),
            If(self.clear_sat, self.sat.eq(0)).Elif(adv & v1 & ~self.bypass & ovf, self.sat.eq(1)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        N, CW, DW = self.kernel_size**2, self.coeff_width, self.data_width
        self._coeff_index = CSRStorage(bits_for(N - 1), name="coeff_index", description="Shadow coefficient index (auto-increments on a value write).")
        self._coeff_value = CSRStorage(CW, name="coeff_value", description="Writing loads the shadow coefficient at coeff_index (signed).")
        self._shift_offset = CSRStorage(fields=[
            CSRField("shift",  size=4,      offset=0,  reset=self.shift.reset.value,  description="Right shift of the sum."),
            CSRField("offset", size=DW + 1, offset=8,  reset=self.offset.reset.value & ((1 << (DW + 1)) - 1), description="Signed offset added after the shift."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("commit",     size=1, offset=0, pulse=True, description="Copy the shadow set at the next frame start."),
            CSRField("commit_now", size=1, offset=1, pulse=True, description="Copy the shadow set immediately."),
            CSRField("bypass",     size=1, offset=2, description="Pass the window centre (same latency)."),
            CSRField("clear_sat",  size=1, offset=3, pulse=True, description="Clear the saturation flag."),
            CSRField("clear",      size=1, offset=4, pulse=True, description="Clear the geometry error."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("commit_pending", size=1, offset=0, description="A commit waits for the next frame start."),
            CSRField("sat",            size=1, offset=1, description="Sticky: an output clamped."),
            CSRField("geometry_error", size=1, offset=2, description="Sticky: line length changed or exceeded max_width."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("kernel_size", size=4, offset=0, description="Kernel size."),
            CSRField("coeff_width", size=5, offset=8, description="Coefficient width."),
            CSRField("n_channels",  size=2, offset=16, description="Channels."),
        ])
        # The index register is owned by the block (auto-increment): a CSR write reloads it.
        self.sync += If(self._coeff_index.re, self.coeff_index.eq(self._coeff_index.storage))
        self.comb += [
            self.coeff_value.eq(self._coeff_value.storage), self.coeff_we.eq(self._coeff_value.re),
            self.shift.eq(self._shift_offset.fields.shift), self.offset.eq(self._shift_offset.fields.offset),
            self.commit.eq(self._control.fields.commit), self.commit_now.eq(self._control.fields.commit_now),
            self.bypass.eq(self._control.fields.bypass), self.clear_sat.eq(self._control.fields.clear_sat),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.commit_pending.eq(self.commit_pending), self._status.fields.sat.eq(self.sat),
            self._status.fields.geometry_error.eq(self.geometry_error),
            self._config.fields.kernel_size.eq(self.kernel_size), self._config.fields.coeff_width.eq(self.coeff_width),
            self._config.fields.n_channels.eq(self.n_channels),
        ]
