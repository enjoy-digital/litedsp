#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Constant false-alarm rate detectors on cell streams (range profiles, range-Doppler map rows)."""

from functools import reduce
from operator  import add

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, real_layout, cell_layout

CFAR_CA, CFAR_GO, CFAR_SO = 0, 1, 2

# CA-CFAR ------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCACFAR(LiteXModule):
    """One-dimensional cell-averaging CFAR detector on framed cell streams.

    A window of ``2*(n_train + n_guard) + 1`` cells slides along each frame (a range profile or a
    map row): the cell under test sits in the middle, ``n_guard`` cells on each side are
    ignored and the ``n_train`` leading and lagging training cells form the noise estimate.
    Runtime ``mode``: 0 cell averaging (``lead + lag``), 1 greatest-of (``2*max``), 2
    smallest-of (``2*min``). The threshold is ``alpha * mean`` (``alpha`` unsigned
    Q(alpha_width - threshold_frac).threshold_frac, see ``litedsp.radar.design.cfar_alpha``),
    computed as ``sum * alpha * round(2**16 / (2*n_train))``, rounded and floored at the runtime
    ``threshold_min`` (the zero-padded edges see smaller training sums). Frames are
    zero-padded: ``first`` clears the window, and after ``last`` the block flushes the trailing
    cells with zero neighbours (``n_train + n_guard + 1`` cycles ``sink.ready`` low), so the output has exactly one
    beat per input cell with the same framing. Output: the cell, its threshold and the
    decision on :func:`~litedsp.common.cell_layout`. ``latency = None`` (the flush); nominal
    delay ``n_train + n_guard + 4`` cycles.
    """
    def __init__(self, n_train=8, n_guard=2, data_width=17, alpha_width=16, threshold_frac=8,
        with_csr=True):
        check(1 <= n_train <= 32, "expected 1 <= n_train <= 32")
        check(0 <= n_guard <= 8, "expected 0 <= n_guard <= 8")
        check(0 < threshold_frac < alpha_width, "expected 0 < threshold_frac < alpha_width")
        self.n_train        = n_train
        self.n_guard        = n_guard
        self.data_width     = data_width
        self.alpha_width    = alpha_width
        self.threshold_frac = threshold_frac
        self.latency        = None
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(cell_layout(data_width))
        self.alpha         = Signal(alpha_width, reset=int(round(2.0*(1 << threshold_frac))))
        self.mode          = Signal(2)
        self.threshold_min = Signal(data_width)                         # Threshold floor (noise).
        self.detections    = Signal(32)                                 # Detections since reset.

        # # #

        T, G = n_train, n_guard
        H    = T + G                                                    # Half window.
        L    = 2*H + 1
        adv, xfer = Signal(), Signal()
        step, cell_in = Signal(), Signal()                              # Window step, real cell.
        self.comb += adv.eq(self.source.ready | ~self.source.valid)

        # Sliding window (registered cells with a 'real' flag and the frame tags).
        # -----------------------------------------------------------------------
        cells = [Signal(data_width, name=f"cell{k}") for k in range(L)]
        real  = [Signal(name=f"real{k}") for k in range(L)]
        firsts = [Signal(name=f"first{k}") for k in range(L)]
        lasts  = [Signal(name=f"last{k}") for k in range(L)]
        x_in = Signal(data_width)
        self.comb += x_in.eq(Mux(cell_in, self.sink.data, 0))
        shift = [
            cells[0].eq(x_in), real[0].eq(cell_in),
            firsts[0].eq(cell_in & self.sink.first), lasts[0].eq(cell_in & self.sink.last),
        ]
        for k in range(1, L):
            shift += [cells[k].eq(cells[k - 1]), real[k].eq(real[k - 1]),
                      firsts[k].eq(firsts[k - 1]), lasts[k].eq(lasts[k - 1])]
        clear = [c.eq(0) for c in cells] + [r.eq(0) for r in real] + [f.eq(0) for f in firsts] + [l.eq(0) for l in lasts]

        # Frame FSM: RUN consumes cells (a 'first' cell restarts the window), FLUSH pushes H+1
        # zeros after 'last' so the trailing cells reach the centre and are captured.
        # ---------------------------------------------------------------------------------
        flush_cnt = Signal(max=H + 2)
        self.fsm  = fsm = FSM(reset_state="RUN")
        fsm.act("RUN",
            self.sink.ready.eq(adv),
            cell_in.eq(self.sink.valid),
            step.eq(adv & self.sink.valid),
            If(step & self.sink.last,
                NextValue(flush_cnt, H + 1),
                NextState("FLUSH"),
            ),
        )
        fsm.act("FLUSH",
            step.eq(adv),
            If(step,
                If(flush_cnt == 1, NextState("RUN")).Else(NextValue(flush_cnt, flush_cnt - 1)),
            ),
        )
        self.comb += xfer.eq(step)
        self.sync += If(step,
            If(cell_in & self.sink.first, *clear, cells[0].eq(self.sink.data), real[0].eq(1),
               firsts[0].eq(1), lasts[0].eq(self.sink.last)
            ).Else(*shift),
        )

        # Stage 1: training sums, the cell under test and its tags.
        # ---------------------------------------------------------
        SW   = data_width + (2*T).bit_length()
        lead = Signal(SW)
        lag  = Signal(SW)
        cut1, cut1_v, first1, last1 = Signal(data_width), Signal(), Signal(), Signal()
        self.sync += If(adv,
            lead.eq(reduce(add, cells[0:T])),
            lag.eq(reduce(add, cells[H + G + 1:H + G + 1 + T])),
            cut1.eq(cells[H]), cut1_v.eq(step & real[H]), first1.eq(firsts[H]), last1.eq(lasts[H]),
        )

        # Stages 2-4: statistic * alpha * recip -> rounded threshold, compare.
        # --------------------------------------------------------------------
        recip = int(round((1 << 16)/(2*T)))
        stat  = Signal(SW + 1)
        p1    = Signal(SW + 1 + alpha_width)
        p2    = Signal(SW + 1 + alpha_width + 17)
        cut2, cut2_v, first2, last2 = Signal(data_width), Signal(), Signal(), Signal()
        cut3, cut3_v, first3, last3 = Signal(data_width), Signal(), Signal(), Signal()
        mx = Signal(SW)
        mn = Signal(SW)
        self.comb += [
            mx.eq(Mux(lead > lag, lead, lag)),
            mn.eq(Mux(lead > lag, lag, lead)),
            stat.eq(Mux(self.mode == CFAR_GO, mx << 1, Mux(self.mode == CFAR_SO, mn << 1, lead + lag))),
        ]
        thr_full = Signal(SW + 1 + alpha_width + 17)
        thr_r    = Signal(SW + 1 + alpha_width + 1)
        thr_c    = Signal(data_width)
        thr      = Signal(data_width)
        self.comb += [
            thr_full.eq(p2 + (1 << (threshold_frac + 15))),
            thr_r.eq(thr_full >> (threshold_frac + 16)),
            thr_c.eq(Mux(thr_r > (1 << data_width) - 1, (1 << data_width) - 1, thr_r)),
            thr.eq(Mux(thr_c < self.threshold_min, self.threshold_min, thr_c)),
        ]
        detect = Signal()
        self.comb += detect.eq(cut3 > thr)
        self.sync += [
            If(adv,
                p1.eq(stat*self.alpha), cut2.eq(cut1), cut2_v.eq(cut1_v), first2.eq(first1), last2.eq(last1),
                p2.eq(p1*recip),        cut3.eq(cut2), cut3_v.eq(cut2_v), first3.eq(first2), last3.eq(last2),
                self.source.valid.eq(cut3_v),
                self.source.data.eq(cut3),
                self.source.threshold.eq(thr),
                self.source.detect.eq(detect),
                self.source.first.eq(first3),
                self.source.last.eq(last3),
            ),
            If(adv & cut3_v & detect, self.detections.eq(self.detections + 1)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._alpha = CSRStorage(self.alpha_width, reset=self.alpha.reset.value, name="alpha",
            description=f"Threshold factor on the training mean (unsigned Q.{self.threshold_frac}).")
        self._control = CSRStorage(fields=[
            CSRField("mode", size=2, offset=0, description="0: cell averaging, 1: greatest-of, 2: smallest-of."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_train", size=8, offset=0, description="Training cells per side."),
            CSRField("n_guard", size=8, offset=8, description="Guard cells per side."),
            CSRField("frac",    size=8, offset=16, description="Fractional bits of alpha."),
        ])
        self._threshold_min = CSRStorage(self.data_width, name="threshold_min",
            description="Threshold floor (unsigned cell units): guards the zero-padded edges and notches.")
        self._detections = CSRStatus(32, name="detections", description="Detections since reset.")
        self.comb += [
            self.alpha.eq(self._alpha.storage),
            self.mode.eq(self._control.fields.mode),
            self.threshold_min.eq(self._threshold_min.storage),
            self._config.fields.n_train.eq(self.n_train),
            self._config.fields.n_guard.eq(self.n_guard),
            self._config.fields.frac.eq(self.threshold_frac),
            self._detections.status.eq(self.detections),
        ]
