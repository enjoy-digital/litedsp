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

# Shared engine ------------------------------------------------------------------------------------

class _CFARWindow:
    """Signals of the sliding window built by :func:`_cfar_window`."""

def _cfar_window(self, T, G, adv):
    """Sliding window of ``2*(T+G)+1`` cells with the cell under test in the centre: RUN consumes
    cells (a 'first' cell restarts the window), FLUSH pushes T+G+1 zeros after 'last' so the
    trailing cells reach the centre and are captured. Returns the window signals plus the stage-1
    registers of the cell under test (``cut1``, ``cut1_v``, ``first1``, ``last1``); ``lead`` /
    ``lag`` are the training-cell lists."""
    H, L = T + G, 2*(T + G) + 1
    dw   = len(self.sink.data)
    w    = _CFARWindow()
    step, cell_in = Signal(), Signal()
    cells  = [Signal(dw, name=f"cell{k}") for k in range(L)]
    real   = [Signal(name=f"real{k}") for k in range(L)]
    firsts = [Signal(name=f"first{k}") for k in range(L)]
    lasts  = [Signal(name=f"last{k}") for k in range(L)]
    x_in = Signal(dw)
    self.comb += x_in.eq(Mux(cell_in, self.sink.data, 0))
    shift = [
        cells[0].eq(x_in), real[0].eq(cell_in),
        firsts[0].eq(cell_in & self.sink.first), lasts[0].eq(cell_in & self.sink.last),
    ]
    for k in range(1, L):
        shift += [cells[k].eq(cells[k - 1]), real[k].eq(real[k - 1]),
                  firsts[k].eq(firsts[k - 1]), lasts[k].eq(lasts[k - 1])]
    clear = [c.eq(0) for c in cells] + [r.eq(0) for r in real] + [f.eq(0) for f in firsts] + [
        l.eq(0) for l in lasts]
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
    self.sync += If(step,
        If(cell_in & self.sink.first, *clear, cells[0].eq(self.sink.data), real[0].eq(1),
           firsts[0].eq(1), lasts[0].eq(self.sink.last)
        ).Else(*shift),
    )
    w.cells, w.step = cells, step
    w.lead = cells[0:T]
    w.lag  = cells[H + G + 1:H + G + 1 + T]
    w.cut1, w.cut1_v, w.first1, w.last1 = Signal(dw), Signal(), Signal(), Signal()
    self.sync += If(adv,
        w.cut1.eq(cells[H]), w.cut1_v.eq(step & real[H]), w.first1.eq(firsts[H]),
        w.last1.eq(lasts[H]),
    )
    return w

def _cfar_output(self, w, adv, stat, recip):
    """Stages 2-4 shared by the 1-D detectors: ``stat * alpha`` -> ``* recip`` -> rounded by
    ``threshold_frac + 16``, saturated to the cell width, floored at ``threshold_min``; the
    decision, the output register and the detection counter."""
    dw, aw, frac = self.data_width, self.alpha_width, self.threshold_frac
    SW = len(stat)
    p1 = Signal(SW + aw)
    p2 = Signal(SW + aw + 17)
    cut2, cut2_v, first2, last2 = Signal(dw), Signal(), Signal(), Signal()
    cut3, cut3_v, first3, last3 = Signal(dw), Signal(), Signal(), Signal()
    thr_full = Signal(SW + aw + 17)
    thr_r    = Signal(SW + aw + 1)
    thr_c    = Signal(dw)
    thr      = Signal(dw)
    detect   = Signal()
    self.comb += [
        thr_full.eq(p2 + (1 << (frac + 15))),
        thr_r.eq(thr_full >> (frac + 16)),
        thr_c.eq(Mux(thr_r > (1 << dw) - 1, (1 << dw) - 1, thr_r)),
        thr.eq(Mux(thr_c < self.threshold_min, self.threshold_min, thr_c)),
        detect.eq(cut3 > thr),
    ]
    self.sync += [
        If(adv,
            p1.eq(stat*self.alpha), cut2.eq(w.cut1), cut2_v.eq(w.cut1_v), first2.eq(w.first1),
            last2.eq(w.last1),
            p2.eq(p1*recip),        cut3.eq(cut2),   cut3_v.eq(cut2_v),   first3.eq(first2),
            last3.eq(last2),
            self.source.valid.eq(cut3_v),
            self.source.data.eq(cut3),
            self.source.threshold.eq(thr),
            self.source.detect.eq(detect),
            self.source.first.eq(first3),
            self.source.last.eq(last3),
        ),
        If(adv & cut3_v & detect, self.detections.eq(self.detections + 1)),
    ]

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
    cells with zero neighbours (``n_train + n_guard + 1`` cycles
    ``sink.ready`` low), so the output has exactly one
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
        adv  = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        w = _cfar_window(self, T, G, adv)

        # Stage 1: training sums, the cell under test and its tags.
        # ---------------------------------------------------------
        SW   = data_width + (2*T).bit_length()
        lead = Signal(SW)
        lag  = Signal(SW)
        self.sync += If(adv,
            lead.eq(reduce(add, w.lead)),
            lag.eq(reduce(add, w.lag)),
        )

        # Statistic: CA / greatest-of / smallest-of, then the shared threshold pipeline.
        # ------------------------------------------------------------------------------
        stat = Signal(SW + 1)
        mx   = Signal(SW)
        mn   = Signal(SW)
        self.comb += [
            mx.eq(Mux(lead > lag, lead, lag)),
            mn.eq(Mux(lead > lag, lag, lead)),
            stat.eq(
                Mux(self.mode == CFAR_GO, mx << 1, Mux(self.mode == CFAR_SO, mn << 1, lead + lag))),
        ]
        _cfar_output(self, w, adv, stat, recip=int(round((1 << 16)/(2*T))))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._alpha = CSRStorage(self.alpha_width, reset=self.alpha.reset.value, name="alpha",
            description=f"Threshold factor on the training mean (unsigned "
                        f"Q.{self.threshold_frac}).")
        self._control = CSRStorage(fields=[
            CSRField("mode", size=2, offset=0, description="0: cell averaging, 1: greatest-of, 2: smallest-of."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_train", size=8, offset=0, description="Training cells per side."),
            CSRField("n_guard", size=8, offset=8, description="Guard cells per side."),
            CSRField("frac",    size=8, offset=16, description="Fractional bits of alpha."),
        ])
        self._threshold_min = CSRStorage(self.data_width, name="threshold_min",
            description="Threshold floor (unsigned cell units): guards the zero-padded edges and "
                        "notches.")
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

# OS-CFAR ------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPOSCFAR(LiteXModule):
    """One-dimensional ordered-statistic CFAR detector on framed cell streams.

    Same sliding window, zero padding and flush as :class:`LiteDSPCACFAR`, but the noise
    estimate is the ``rank``-th smallest (0-based, runtime) of the ``2*n_train`` training cells,
    which a single interferer or a neighbouring target cannot capture (a CA mean would). The
    rank is found in parallel (``(2T)^2`` comparators, ``n_train <= 8``): each training cell
    counts the cells below it (ties broken by position) and the one whose count equals the rank
    is selected. ``threshold = rounded(stat * alpha, threshold_frac)`` saturated and floored
    at ``threshold_min``; ``rank`` resets to ``round(0.75 * 2T) - 1`` (the usual 3/4 quantile).
    Output on :func:`~litedsp.common.cell_layout`; ``latency = None`` (the flush).
    """
    def __init__(self, n_train=4, n_guard=2, rank=None, data_width=17, alpha_width=16,
                 threshold_frac=8,
        with_csr=True):
        check(1 <= n_train <= 8, "expected 1 <= n_train <= 8")
        check(0 <= n_guard <= 8, "expected 0 <= n_guard <= 8")
        check(0 < threshold_frac < alpha_width, "expected 0 < threshold_frac < alpha_width")
        K = 2*n_train
        if rank is None:
            rank = max(0, int(round(0.75*K)) - 1)
        check(0 <= rank < K, "expected 0 <= rank < 2*n_train")
        self.n_train        = n_train
        self.n_guard        = n_guard
        self.data_width     = data_width
        self.alpha_width    = alpha_width
        self.threshold_frac = threshold_frac
        self.latency        = None
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(cell_layout(data_width))
        self.alpha         = Signal(alpha_width, reset=int(round(4.0*(1 << threshold_frac))))
        self.rank          = Signal(max=K, reset=rank)
        self.threshold_min = Signal(data_width)
        self.detections    = Signal(32)

        # # #

        adv = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        w = _cfar_window(self, n_train, n_guard, adv)

        # Stage 1: rank selection over the training cells (ties broken by position).
        # ----------------------------------------------------------------------------
        train = w.lead + w.lag
        stat  = Signal(data_width)
        sel   = Signal(data_width)
        counts = []
        for j, vj in enumerate(train):
            below = [Mux((vi < vj) | ((vi == vj) & (i < j)), 1, 0) for i,
                     vi in enumerate(train) if i != j]
            c = Signal(max=K)
            self.comb += c.eq(reduce(add, below) if below else 0)
            counts.append(c)
        self.comb += sel.eq(reduce(lambda a, b: a | b,
                                   [Mux(counts[j] == self.rank, train[j], 0) for j in range(K)]))
        self.sync += If(adv, stat.eq(sel))
        _cfar_output(self, w, adv, stat, recip=1 << 16)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._alpha = CSRStorage(self.alpha_width, reset=self.alpha.reset.value, name="alpha",
            description=f"Threshold factor on the ranked training cell (unsigned "
                        f"Q.{self.threshold_frac}).")
        self._control = CSRStorage(fields=[
            CSRField("rank", size=len(self.rank), offset=0, reset=self.rank.reset.value,
                description="0-based rank of the training cell used as the noise estimate."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_train", size=8, offset=0,  description="Training cells per side."),
            CSRField("n_guard", size=8, offset=8,  description="Guard cells per side."),
            CSRField("frac",    size=8, offset=16, description="Fractional bits of alpha."),
        ])
        self._threshold_min = CSRStorage(self.data_width, name="threshold_min",
            description="Threshold floor (unsigned cell units).")
        self._detections = CSRStatus(32, name="detections", description="Detections since reset.")
        self.comb += [
            self.alpha.eq(self._alpha.storage),
            self.rank.eq(self._control.fields.rank),
            self._config.fields.n_train.eq(self.n_train),
            self._config.fields.n_guard.eq(self.n_guard),
            self._config.fields.frac.eq(self.threshold_frac),
            self.threshold_min.eq(self._threshold_min.storage),
            self._detections.status.eq(self.detections),
        ]
