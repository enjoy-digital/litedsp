#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Two-dimensional cell-averaging CFAR on range-Doppler maps streamed row by row."""

from functools import reduce
from operator  import add

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, real_layout, cell_layout

# 2-D CA-CFAR --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCFAR2D(LiteXModule):
    """Cell-averaging CFAR over a ``(2R+1) x (2C+1)`` box of a range-Doppler map.

    The map arrives as ``n_range_bins`` frames (rows) of ``n_doppler_bins`` cells (the corner
    turn / Doppler processor order, rows counted from reset); ``R = n_train[0] + n_guard[0]``
    rows and ``C = n_train[1] + n_guard[1]`` cells on each side of the cell under test form the
    box, the inner ``(2*n_guard[0]+1) x (2*n_guard[1]+1)`` guard box is excluded, so the
    training sum spans ``n_training = box - guard`` cells. The last ``2R+1`` rows live in a line
    buffer (one write and four read ports: the row leaving the box, the rows entering and
    leaving the guard box and the centre row; the RAM is replicated by synthesis), the vertical
    column sums of both boxes are kept in two ``n_doppler_bins``-entry RAMs and slide by one row
    per incoming row, and a ``2C+1``-wide shift register slides horizontally. Edges are zero
    padded: ``C`` virtual cells after each row and ``R`` virtual rows after each CPI are flushed
    with ``sink.ready`` low, so the output has one cell per input cell in the same order and
    framing (throughput ``M / (M + C)``). Threshold ``sum * alpha * round(2**16 / n_training)``
    rounded, saturated and floored at the runtime ``threshold_min``, ``alpha`` unsigned
    Q(alpha_width - threshold_frac).threshold_frac
    (see ``litedsp.radar.design.cfar_alpha``). A ``first``/``last`` at the wrong position sets
    the sticky ``frame_error`` and re-synchronises the row. ``latency = None``.
    """
    def __init__(self, n_range_bins=64, n_doppler_bins=16, n_train=(4, 2), n_guard=(1, 1),
        data_width=17, alpha_width=16, threshold_frac=8, with_csr=True):
        n_train, n_guard = tuple(n_train), tuple(n_guard)
        check(len(n_train) == 2 and len(n_guard) == 2,
              "expected n_train / n_guard as (range, doppler) pairs")
        check(1 <= n_train[0] <= 16 and 1 <= n_train[1] <= 16, "expected 1 <= n_train <= 16")
        check(0 <= n_guard[0] <= 4 and 0 <= n_guard[1] <= 4, "expected 0 <= n_guard <= 4")
        check(0 < threshold_frac < alpha_width, "expected 0 < threshold_frac < alpha_width")
        R, C   = n_train[0] + n_guard[0], n_train[1] + n_guard[1]
        gr, gd = n_guard
        N, M   = n_range_bins, n_doppler_bins
        check(N > 2*R and M > 2*C, "expected n_range_bins > 2*(n_train[0]+n_guard[0]) and "
                                   "n_doppler_bins > 2*(n_train[1]+n_guard[1])")
        self.n_range_bins   = N
        self.n_doppler_bins = M
        self.n_train        = n_train
        self.n_guard        = n_guard
        self.n_training     = (2*R + 1)*(2*C + 1) - (2*gr + 1)*(2*gd + 1)
        self.data_width     = data_width
        self.alpha_width    = alpha_width
        self.threshold_frac = threshold_frac
        self.latency        = None
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(cell_layout(data_width))
        self.alpha         = Signal(alpha_width, reset=int(round(2.0*(1 << threshold_frac))))
        self.threshold_min = Signal(data_width)                         # Threshold floor (noise).
        self.clear       = Signal()
        self.frame_error = Signal()
        self.detections  = Signal(32)

        # # #

        slots = 2*R + 1
        adv   = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)

        # Beat sequencer: real cells in RUN, virtual columns / rows in FLUSH.
        # -------------------------------------------------------------------
        col   = Signal(max=M + C)                                       # S0 column (>= M: virtual).
        row   = Signal(max=N + R)                                       # S0 row (>= N: virtual).
        beat  = Signal()                                                # A beat enters S0.
        real0 = Signal()                                                # Real input cell.
        x0    = Signal(data_width)
        xfer  = Signal()
        self.fsm = fsm = FSM(reset_state="RUN")
        fsm.act("RUN",
            self.sink.ready.eq(adv),
            beat.eq(adv & self.sink.valid),
            real0.eq(1),
            x0.eq(self.sink.data),
            If(beat & (col == M - 1),
                NextState("FLUSH"),
            ),
        )
        end_of_row = Signal()
        fsm.act("FLUSH",
            beat.eq(adv),
            If(beat & end_of_row,
                If(row < N - 1,
                    NextState("RUN"),
                ).Elif(row == N + R - 1,
                    NextState("RUN"),
                ),
            ),
        )
        self.comb += [
            xfer.eq(self.sink.valid & self.sink.ready),
            end_of_row.eq(col == M + C - 1),
        ]
        self.sync += [
            If(beat,
                If(real0 & self.sink.first,
                    col.eq(1),
                ).Elif(end_of_row,
                    col.eq(0),
                    If(row == N + R - 1, row.eq(0)).Else(row.eq(row + 1)),
                ).Else(
                    col.eq(col + 1),
                ),
            ),
            # Frame monitor.
            If(self.clear,
                self.frame_error.eq(0),
            ).Elif(xfer & ((self.sink.first != (col == 0)) | (self.sink.last != (col == M - 1))),
                self.frame_error.eq(1),
            ),
        ]

        # Line buffer (2R+1 rows) with per-slot validity, column-sum RAMs.
        # -----------------------------------------------------------------
        CW = data_width + slots.bit_length()
        GW = data_width + (2*gr + 1).bit_length()
        self.specials.mem   = mem   = Memory(data_width, slots*M)
        self.specials.csum  = csum  = Memory(CW, M)
        self.specials.gsum  = gsum  = Memory(GW, M)
        valid = Array(Signal(name=f"rowvalid{k}") for k in range(slots))
        wslot = Signal(max=slots)                                       # Slot of the incoming row.
        self.sync += If(beat & end_of_row,
            If(wslot == slots - 1, wslot.eq(0)).Else(wslot.eq(wslot + 1)),
        )
        def slot_back(k):                                               # (wslot - k) mod slots.
            s = Signal(max=slots)
            d = Signal((wslot.nbits + 2, True))
            self.comb += [d.eq(wslot - (k % slots)), If(d < 0, s.eq((d + slots)[:s.nbits])).Else(
                s.eq(d[:s.nbits]))]
            return s
        # Rows relative to the incoming row: the one leaving the box, entering / leaving the guard
        # box and the centre row.
        rel = {name: slot_back(k) for name, k in
               (("leave", slots), ("gin", R - gr), ("gout", R + gr + 1), ("centre", R))}
        col_ok = Signal()
        self.comb += col_ok.eq(col < M)
        ports = {}
        for name in ("leave", "gin", "gout", "centre"):
            p = mem.get_port(has_re=True)
            self.specials += p
            self.comb += [p.adr.eq(rel[name]*M + col), p.re.eq(adv)]
            ports[name] = p
        wp = mem.get_port(write_capable=True)
        cs_rp = csum.get_port(has_re=True)
        cs_wp = csum.get_port(write_capable=True)
        gs_rp = gsum.get_port(has_re=True)
        gs_wp = gsum.get_port(write_capable=True)
        self.specials += wp, cs_rp, cs_wp, gs_rp, gs_wp
        self.comb += [cs_rp.adr.eq(col[:cs_rp.adr.nbits]), cs_rp.re.eq(adv),
                      gs_rp.adr.eq(col[:gs_rp.adr.nbits]), gs_rp.re.eq(adv)]

        # S1: registered beat + read masks.
        # ---------------------------------
        v1, x1, real1, colok1, row1_v = Signal(), Signal(data_width), Signal(), Signal(), Signal()
        col1  = Signal(max=M + C)
        row1  = Signal(max=N + R)
        wslot1 = Signal(max=slots)
        masks1 = {name: Signal(name=f"{name}_ok") for name in ("leave", "gin", "gout", "centre")}
        first_row = Signal()
        self.comb += first_row.eq(row == 0)
        self.sync += If(adv,
            v1.eq(beat), x1.eq(Mux(real0 & (row < N), x0, 0)), real1.eq(real0 & (row < N)),
            colok1.eq(col_ok),
            col1.eq(col), row1.eq(row), wslot1.eq(wslot), row1_v.eq(row < N),
            *[masks1[name].eq(valid[rel[name]] & ~first_row & col_ok) for name in masks1],
        )

        # S1 arithmetic: slide the column sums by one row, write the cell, push horizontally.
        # -----------------------------------------------------------------------------------
        leave_v, gin_v, gout_v, centre_v = [
            Signal(data_width, name=n) for n in ("leave_v", "gin_v", "gout_v", "centre_v")]
        self.comb += [
            leave_v.eq(Mux(masks1["leave"], ports["leave"].dat_r, 0)),
            gin_v.eq(Mux(masks1["gin"], ports["gin"].dat_r, 0)),
            gout_v.eq(Mux(masks1["gout"], ports["gout"].dat_r, 0)),
            centre_v.eq(Mux(masks1["centre"], ports["centre"].dat_r, 0)),
        ]
        cs_base, gs_base = Signal(CW), Signal(GW)
        cs_new,  gs_new  = Signal(CW), Signal(GW)
        self.comb += [
            cs_base.eq(Mux(row1 == 0, 0, cs_rp.dat_r)),
            gs_base.eq(Mux(row1 == 0, 0, gs_rp.dat_r)),
            cs_new.eq(cs_base + x1 - leave_v),
            gs_new.eq(gs_base + gin_v - gout_v),
            # Writes: the incoming real cell (after the S0 read of the leaving value at the same
            # address), the slid column sums for real columns.
            wp.adr.eq(wslot1*M + col1), wp.dat_w.eq(x1), wp.we.eq(adv & v1 & real1 & colok1),
            cs_wp.adr.eq(col1[:cs_wp.adr.nbits]), cs_wp.dat_w.eq(cs_new),
            cs_wp.we.eq(adv & v1 & colok1),
            gs_wp.adr.eq(col1[:gs_wp.adr.nbits]), gs_wp.dat_w.eq(gs_new),
            gs_wp.we.eq(adv & v1 & colok1),
        ]
        # Row validity: latched at the end of each row (a real row validates its slot, a virtual
        # row invalidates the row it replaced) so the leaving-row reads of the row in progress
        # still see the slot's previous state; all cleared at the CPI start.
        self.sync += If(adv & v1 & colok1,
            If(row1 == 0,
                *[valid[k].eq(0) for k in range(slots)],
            ),
            If(col1 == M - 1,
                *[If(wslot1 == k, valid[k].eq(real1)) for k in range(slots)],   # Explicit decode:
            ),                                                               # Array writes lower to
        )                                                                    # blocking temporaries.


        # S2: horizontal shift registers (2C+1 wide) of column sums, centre cells and tags.
        # ---------------------------------------------------------------------------------
        W = 2*C + 1
        hs_c = [Signal(CW, name=f"hs_c{k}") for k in range(W)]
        hs_g = [Signal(GW, name=f"hs_g{k}") for k in range(W)]
        hs_x = [Signal(data_width, name=f"hs_x{k}") for k in range(W)]
        hs_v = [Signal(name=f"hs_v{k}") for k in range(W)]
        hs_f = [Signal(name=f"hs_f{k}") for k in range(W)]
        hs_l = [Signal(name=f"hs_l{k}") for k in range(W)]
        v2   = Signal()
        push = [
            hs_c[0].eq(Mux(colok1, cs_new, 0)), hs_g[0].eq(Mux(colok1, gs_new, 0)),
            hs_x[0].eq(Mux(colok1, centre_v, 0)),
            hs_v[0].eq(colok1 & masks1["centre"]),
            hs_f[0].eq(col1 == 0), hs_l[0].eq(col1 == M - 1),
        ]
        for k in range(1, W):
            push += [hs_c[k].eq(hs_c[k - 1]), hs_g[k].eq(hs_g[k - 1]), hs_x[k].eq(hs_x[k - 1]),
                     hs_v[k].eq(hs_v[k - 1]), hs_f[k].eq(hs_f[k - 1]), hs_l[k].eq(hs_l[k - 1])]
        clear_hs = [s.eq(0)
                         for s in hs_c[1:] + hs_g[1:] + hs_x[1:] + hs_v[1:] + hs_f[1:] + hs_l[1:]]
        self.sync += If(adv,
            v2.eq(v1),
            If(v1,
                *push,
                If(col1 == 0, *clear_hs),
            ),
        )

        # S3..S6: box sums, training sum, threshold, decision.
        # ----------------------------------------------------
        BW = CW + W.bit_length()
        HW = GW + (2*gd + 1).bit_length()
        big, guard = Signal(BW), Signal(HW)
        x3, v3, f3, l3 = Signal(data_width), Signal(), Signal(), Signal()
        self.sync += If(adv,
            big.eq(reduce(add, hs_c)),
            guard.eq(reduce(add, hs_g[C - gd:C + gd + 1])),
            x3.eq(hs_x[C]), v3.eq(v2 & hs_v[C]), f3.eq(hs_f[C]), l3.eq(hs_l[C]),
        )
        recip = int(round((1 << 16)/self.n_training))
        train = Signal(BW)
        p1    = Signal(BW + alpha_width)
        p2    = Signal(BW + alpha_width + 17)
        x4, v4, f4, l4 = Signal(data_width), Signal(), Signal(), Signal()
        x5, v5, f5, l5 = Signal(data_width), Signal(), Signal(), Signal()
        x6, v6, f6, l6 = Signal(data_width), Signal(), Signal(), Signal()
        thr_full = Signal(BW + alpha_width + 17)
        thr_r    = Signal(BW + alpha_width + 1)
        thr_c    = Signal(data_width)
        thr      = Signal(data_width)
        detect   = Signal()
        self.comb += [
            thr_full.eq(p2 + (1 << (threshold_frac + 15))),
            thr_r.eq(thr_full[threshold_frac + 16:]),
            thr_c.eq(Mux(thr_r > (1 << data_width) - 1, (1 << data_width) - 1, thr_r[:data_width])),
            thr.eq(Mux(thr_c < self.threshold_min, self.threshold_min, thr_c)),
            detect.eq(x6 > thr),
        ]
        self.sync += [
            If(adv,
                train.eq(big - guard), x4.eq(x3), v4.eq(v3), f4.eq(f3), l4.eq(l3),
                p1.eq(train*self.alpha), x5.eq(x4), v5.eq(v4), f5.eq(f4), l5.eq(l4),
                p2.eq(p1*recip),        x6.eq(x5), v6.eq(v5), f6.eq(f5), l6.eq(l5),
                self.source.valid.eq(v6),
                self.source.data.eq(x6),
                self.source.threshold.eq(thr),
                self.source.detect.eq(detect),
                self.source.first.eq(f6),
                self.source.last.eq(l6),
            ),
            If(adv & v6 & detect, self.detections.eq(self.detections + 1)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._alpha = CSRStorage(self.alpha_width, reset=self.alpha.reset.value, name="alpha",
            description=f"Threshold factor on the training mean (unsigned "
                        f"Q.{self.threshold_frac}).")
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the frame error."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_training", size=16, offset=0,  description="Training cells in the box."),
            CSRField("frac",       size=8,  offset=16, description="Fractional bits of alpha."),
            CSRField("two_d",      size=1,  offset=24, description="1: n_training is the 2-D box count."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("frame_error", size=1, offset=0, description="Sticky: row framing did not match n_doppler_bins."),
        ])
        self._threshold_min = CSRStorage(self.data_width, name="threshold_min",
            description="Threshold floor (unsigned cell units): guards the zero-padded edges and "
                        "notches.")
        self._detections = CSRStatus(32, name="detections", description="Detections since reset.")
        self.comb += [
            self.alpha.eq(self._alpha.storage),
            self.threshold_min.eq(self._threshold_min.storage),
            self.clear.eq(self._control.fields.clear),
            self._config.fields.n_training.eq(self.n_training),
            self._config.fields.frac.eq(self.threshold_frac),
            self._config.fields.two_d.eq(1),
            self._status.fields.frame_error.eq(self.frame_error),
            self._detections.status.eq(self.detections),
        ]
