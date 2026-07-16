#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Hard- and soft-decision Viterbi decoder for the rate-1/n convolutional encoder.

Decodes the output of :class:`~litedsp.comm.coding.LiteDSPConvEncoder` (same ``constraint``/``polys``
conventions: symbol bit ``k`` is the parity for ``polys[k]``). Fully-parallel add-compare-select
over the ``2**(K-1)`` states with register-exchange survivor paths of depth ``traceback``
(default ``8*K``, well past the ~5K convergence rule of thumb), path metrics normalized by the
global minimum each step. One decoded bit per input symbol; the first ``traceback`` symbols are
absorbed to converge, after which the output stream is bit-aligned to the encoder input.

With ``llr_bits`` set, the sink takes packed signed LLRs (the
:class:`~litedsp.comm.soft_demap.LiteDSPSoftDemapper` convention: positive = bit 0 more likely,
LSB-first slots) and the Hamming branch metric is replaced by the standard max-log metric from
LLRs — only the branch metrics change, the ACS/survivor machinery is shared.  An optional
decision-memory architecture replaces register exchange with packed RAM survivor decisions,
registered best-state reduction, and folded traceback for lower area and higher Fmax.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check

# Helpers ------------------------------------------------------------------------------------------

def _parity_int(v):
    p = 0
    while v:
        p ^= v & 1
        v >>= 1
    return p

def _transitions(constraint, polys):
    """Per-state predecessor table: ``preds[s] = [(p, expected_symbol), ...]``.

    A transition from state ``p`` with input bit ``b`` goes to ``s = (b | p << 1) & mask`` and
    emits symbol bits ``parity(poly & (b | p << 1))`` — mirroring ConvEncoder's shift register.
    """
    n_states = 1 << (constraint - 1)
    mask     = n_states - 1
    preds    = [[] for _ in range(n_states)]
    for p in range(n_states):
        for b in (0, 1):
            full = b | (p << 1)
            sym  = 0
            for k, g in enumerate(polys):
                sym |= _parity_int(g & full) << k
            preds[full & mask].append((p, sym))
    return preds

def _min_tree(pairs, comb):
    """Reduce [(metric, payload)] to the minimum-metric element (ties keep the earlier one)."""
    while len(pairs) > 1:
        nxt = []
        for k in range(0, len(pairs) - 1, 2):
            (m0, p0), (m1, p1) = pairs[k], pairs[k + 1]
            m = Signal(len(m0))
            p = Signal(len(p0))
            comb += If(m1 < m0, m.eq(m1), p.eq(p1)).Else(m.eq(m0), p.eq(p0))
            nxt.append((m, p))
        if len(pairs) % 2:
            nxt.append(pairs[-1])
        pairs = nxt
    return pairs[0]


def _build_decision_memory_decoder(dut, constraint, polys, traceback, llr_bits,
                                   metric_width, normalize_interval):
    """Build a RAM-survivor decoder with folded synchronous traceback.

    ACS accepts one symbol, two registered BEST stages capture the minimum state, optional
    NORMALIZE removes that minimum, then two clocks per survivor step read/consume the decision
    RAM.  The architecture intentionally favors timing/area over symbol throughput.
    """
    n_states = 1 << (constraint - 1)
    n_bits   = len(polys)
    state_bits = constraint - 1
    bm_max = n_bits if llr_bits is None else n_bits*(1 << (llr_bits - 1))
    big = 1 << (metric_width - 2)

    metrics = [Signal(metric_width, reset=(0 if s == 0 else big),
               name=f"metric{s}") for s in range(n_states)]

    # Branch metrics for each possible encoder output symbol.
    bm = {}
    if llr_bits is None:
        for sym in range(1 << n_bits):
            branch = Signal(max=n_bits + 1, name=f"bm{sym}")
            dut.comb += branch.eq(sum((dut.sink.data ^ sym)[k] for k in range(n_bits)))
            bm[sym] = branch
    else:
        sgns, abss = [], []
        for j in range(n_bits):
            llr = Signal((llr_bits, True), name=f"llr{j}")
            ab  = Signal(llr_bits, name=f"llr_abs{j}")
            dut.comb += [
                llr.eq(dut.sink.llrs[j*llr_bits:(j + 1)*llr_bits]),
                ab.eq(Mux(llr < 0, -llr, llr)),
            ]
            sgns.append(llr[-1])
            abss.append(ab)
        for sym in range(1 << n_bits):
            branch = Signal(max=bm_max + 1, name=f"bm{sym}")
            dut.comb += branch.eq(sum(
                Mux(sgns[j] ^ ((sym >> j) & 1), abss[j], 0) for j in range(n_bits)))
            bm[sym] = branch

    # Fully parallel ACS, ending directly at the metric registers and one packed decision row.
    preds, new_ms, choices = _transitions(constraint, polys), [], []
    for s in range(n_states):
        (p0, e0), (p1, e1) = preds[s]
        m0, m1 = Signal(metric_width + 1), Signal(metric_width + 1)
        choice = Signal(name=f"decision{s}")
        metric = Signal(metric_width + 1, name=f"metric_next{s}")
        dut.comb += [
            m0.eq(metrics[p0] + bm[e0]),
            m1.eq(metrics[p1] + bm[e1]),
            choice.eq(m1 < m0),
            metric.eq(Mux(choice, m1, m0)),
        ]
        new_ms.append(metric)
        choices.append(choice)

    decisions = Memory(n_states, traceback, name="survivor_decisions")
    decision_wr = decisions.get_port(write_capable=True)
    decision_rd = decisions.get_port()
    dut.specials += decisions, decision_wr, decision_rd

    write_ptr = Signal(max=traceback)
    trace_ptr = Signal(max=traceback)
    trace_state = Signal(state_bits)
    trace_count = Signal(max=traceback)
    norm_count = Signal(max=max(2, normalize_interval))
    normalize_pending = Signal()
    warmup = Signal(max=traceback + 1, reset=traceback)
    best_state_r = Signal(state_bits)
    best_metric_r = Signal(metric_width)

    # Best-state reduction is isolated from ACS and normalization by registers/FSM states.  Keep
    # each combinational tree at three compare levels for the common K=7/64-state decoder, then
    # reduce the registered group winners in a second three-level tree.  This avoids putting the
    # full six-level global minimum on either the ACS or traceback-control path.
    group_metrics, group_states = [], []
    group_metric_rs, group_state_rs = [], []
    for group, first in enumerate(range(0, n_states, 8)):
        metric, state = _min_tree(
            [(metrics[s], C(s, state_bits)) for s in range(first, min(first + 8, n_states))],
            dut.comb)
        metric_r = Signal(metric_width, name=f"best_group_metric{group}")
        state_r  = Signal(state_bits,  name=f"best_group_state{group}")
        group_metrics.append(metric)
        group_states.append(state)
        group_metric_rs.append(metric_r)
        group_state_rs.append(state_r)
    best_metric, best_state = _min_tree(
        list(zip(group_metric_rs, group_state_rs)), dut.comb)
    pred0 = Array([C(preds[s][0][0], state_bits) for s in range(n_states)])
    pred1 = Array([C(preds[s][1][0], state_bits) for s in range(n_states)])
    decision = Signal()
    predecessor = Signal(state_bits)
    decision_bits = Array([decision_rd.dat_r[s] for s in range(n_states)])
    dut.comb += [
        decision_rd.adr.eq(trace_ptr),
        decision.eq(decision_bits[trace_state]),
        predecessor.eq(Mux(decision, pred1[trace_state], pred0[trace_state])),
    ]

    dut.fsm = fsm = FSM(reset_state="ACS")
    acs = fsm.ongoing("ACS")
    xfer = Signal()
    dut.comb += [
        dut.sink.ready.eq(acs),
        xfer.eq(dut.sink.valid & dut.sink.ready),
        decision_wr.adr.eq(write_ptr),
        decision_wr.dat_w.eq(Cat(*choices)),
        decision_wr.we.eq(xfer),
    ]
    dut.sync += If(xfer,
        *[metrics[s].eq(new_ms[s]) for s in range(n_states)],
        trace_ptr.eq(write_ptr),
        If(write_ptr == traceback - 1, write_ptr.eq(0)).Else(write_ptr.eq(write_ptr + 1)),
        If(norm_count == normalize_interval - 1,
            norm_count.eq(0), normalize_pending.eq(1),
        ).Else(
            norm_count.eq(norm_count + 1), normalize_pending.eq(0),
        ),
        If(warmup != 0, warmup.eq(warmup - 1)),
    )

    fsm.act("ACS",
        If(dut.sink.valid, NextState("BEST_GROUP")),
    )
    fsm.act("BEST_GROUP",
        *[NextValue(group_metric_rs[g], group_metrics[g]) for g in range(len(group_metrics))],
        *[NextValue(group_state_rs[g], group_states[g]) for g in range(len(group_states))],
        NextState("BEST_FINAL"),
    )
    fsm.act("BEST_FINAL",
        NextValue(best_state_r, best_state),
        NextValue(best_metric_r, best_metric),
        If(normalize_pending,
            NextState("NORMALIZE"),
        ).Elif(warmup != 0,
            NextState("ACS"),
        ).Else(
            NextValue(trace_state, best_state),
            NextValue(trace_count, 0),
            NextState("TRACE_READ"),
        ),
    )
    fsm.act("NORMALIZE",
        *[NextValue(metrics[s], metrics[s] - best_metric_r) for s in range(n_states)],
        If(warmup != 0,
            NextState("ACS"),
        ).Else(
            NextValue(trace_state, best_state_r),
            NextValue(trace_count, 0),
            NextState("TRACE_READ"),
        ),
    )
    fsm.act("TRACE_READ",
        NextState("TRACE_STEP"),
    )
    fsm.act("TRACE_STEP",
        NextValue(trace_state, predecessor),
        If(trace_count == traceback - 2,
            NextState("OUTPUT"),
        ).Else(
            NextValue(trace_count, trace_count + 1),
            If(trace_ptr == 0, NextValue(trace_ptr, traceback - 1)
            ).Else(NextValue(trace_ptr, trace_ptr - 1)),
            NextState("TRACE_READ"),
        ),
    )
    fsm.act("OUTPUT",
        dut.source.valid.eq(1),
        dut.source.data.eq(trace_state[0]),
        If(dut.source.ready, NextState("ACS")),
    )

# Viterbi Decoder ----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPViterbiDecoder(LiteXModule):
    """Hard/soft-decision Viterbi decoder (rate 1/n, selectable survivor architecture).

    Hard mode (``llr_bits=None``): ``sink.data`` carries the n coded bits of one symbol and
    the branch metric is the Hamming distance. Soft mode (``llr_bits=k``): ``sink.llrs``
    carries n packed signed k-bit LLRs (slot ``j`` at bits ``[j*k +: k]`` for coded stream
    ``polys[j]``, positive = bit 0 more likely — the soft demapper's convention) and the
    branch metric is the max-log metric: sum over the coded bits of ``|llr_j|`` where the
    LLR sign disagrees with the expected bit (0 where it agrees; an erased/punctured LLR of
    0 is free for both hypotheses). With constant-magnitude (e.g. saturated) LLRs this
    reduces to a scaled Hamming distance, so decisions match the hard decoder exactly.

    Parameters
    ----------
    constraint : int
        Constraint length K, matching the encoder's; the fully-parallel ACS spans
        2**(K-1) states, so resources grow exponentially with K.
    polys : list
        Generator polynomials, octal, matching the encoder's (rate 1/len(polys); default
        (0o171, 0o133): the CCSDS/Voyager K=7 pair).
    traceback : int
        Register-exchange survivor depth in symbols = decoding delay (default 8*K, well
        past the ~5K convergence rule of thumb); each state keeps a traceback-bit register.
    llr_bits : int
        None for hard-decision input; k for soft-decision input (n packed signed k-bit
        LLRs on ``sink.llrs``).
    metric_width : int
        Path-metric register width in bits. With per-step min-normalization the stored
        spread is bounded by (K-1)*bm_max (any state is reachable from the current-minimum
        state in K-1 transitions of at most bm_max = n hard / n*2**(llr_bits-1) soft each),
        and the reset penalty 2**(metric_width-2) must dominate that spread, so
        metric_width >= bits((K-1)*bm_max) + 2 (checked). Default: 10 hard (unchanged),
        max(10, bits((K-1)*bm_max) + 2) soft.
    decision_memory : bool
        Store one predecessor-decision row per symbol and use folded synchronous traceback
        instead of register-exchange survivor paths. Reduces routing/FF pressure but stalls input
        during traceback and emits one decoded bit per traceback operation.
    normalize_interval : int
        Accepted symbols between metric-normalization cycles in decision-memory mode. The global
        minimum and subtract are isolated in separate FSM states rather than the ACS feedback path.
        Nominal ``cycles_per_output`` excludes the one additional normalization clock every
        ``normalize_interval`` accepted symbols and any downstream backpressure.
    """
    def __init__(self, constraint=7, polys=(0o171, 0o133), traceback=None, llr_bits=None,
        metric_width=None, with_csr=True, decision_memory=False, normalize_interval=16):
        n_states  = 1 << (constraint - 1)
        n_bits    = len(polys)
        traceback = traceback or 8*constraint
        check(traceback >= 2, "expected traceback >= 2")
        check(isinstance(decision_memory, bool), "expected decision_memory to be a bool")
        check(normalize_interval >= 1, "expected normalize_interval >= 1")
        if llr_bits is not None:
            check(llr_bits >= 2, "expected llr_bits >= 2 (or None for hard-decision input)")
        # Max branch metric: n mismatches (hard) or n full-scale |LLR|s (soft, |llr| <=
        # 2**(llr_bits-1) for the most negative code).
        bm_max = n_bits if llr_bits is None else n_bits*(1 << (llr_bits - 1))
        # Min-normalized path metrics: spread <= (K-1)*bm_max (see metric_width above); the
        # reset penalty big = 2**(metric_width-2) must exceed it.
        spread_bits = ((constraint - 1)*bm_max).bit_length()
        if metric_width is None:
            metric_width = 10 if llr_bits is None else max(10, spread_bits + 2)
        check(metric_width >= spread_bits + 2,
            f"expected metric_width >= {spread_bits + 2} ((K-1)*bm_max spread + reset headroom)")
        if decision_memory:
            big = 1 << (metric_width - 2)
            check(big + normalize_interval*bm_max < (1 << metric_width),
                "expected metric_width to cover reset penalty + normalize_interval*bm_max")
        self.constraint = constraint
        self.polys      = polys
        self.traceback  = traceback
        self.llr_bits   = llr_bits
        self.decision_memory   = decision_memory
        self.normalize_interval = normalize_interval
        self.traceback_cycles = 2*(traceback - 1) if decision_memory else 0
        self.cycles_per_output = (2*traceback + 2) if decision_memory else 1
        self.latency = None if decision_memory else 1
        if llr_bits is None:
            self.sink = stream.Endpoint([("data", n_bits)])
        else:
            self.sink = stream.Endpoint([("llrs", n_bits*llr_bits)])
        self.source = stream.Endpoint([("data", 1)])

        # # #

        if decision_memory:
            _build_decision_memory_decoder(self, constraint, polys, traceback, llr_bits,
                metric_width, normalize_interval)
            if with_csr:
                self.add_csr()
            return

        # Handshake.
        # ----------
        adv  = Signal()  # Output slot free or being consumed.
        xfer = Signal()  # Input symbol accepted (one ACS step per symbol).
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Path metrics (state 0 favored at reset: the encoder starts zeroed) + survivors.
        # -------------------------------------------------------------------------------
        big     = 1 << (metric_width - 2)  # Large initial penalty, with headroom for branch adds.
        metrics = [Signal(metric_width, reset=(0 if s == 0 else big)) for s in range(n_states)]
        survs   = [Signal(traceback) for s in range(n_states)]

        # Branch metrics for every possible expected symbol value.
        # ----------------------------------------------------------
        # Hard: Hamming distance. Soft (max-log): sum over coded bits of |llr_j| where the
        # LLR sign disagrees with the expected bit (sign bit set = bit 1 more likely).
        bm = {}
        if llr_bits is None:
            for sym in range(1 << n_bits):
                s = Signal(max=n_bits + 1)
                self.comb += s.eq(sum((self.sink.data ^ sym)[k] for k in range(n_bits)))
                bm[sym] = s
        else:
            sgns = []
            abss = []
            for j in range(n_bits):
                llr = Signal((llr_bits, True))
                ab  = Signal(llr_bits)  # |llr| (2**(llr_bits-1) for the most negative code).
                self.comb += [
                    llr.eq(self.sink.llrs[j*llr_bits:(j + 1)*llr_bits]),
                    ab.eq(Mux(llr < 0, -llr, llr)),
                ]
                sgns.append(llr[-1])
                abss.append(ab)
            for sym in range(1 << n_bits):
                s = Signal(max=bm_max + 1)
                self.comb += s.eq(sum(Mux(sgns[j] ^ ((sym >> j) & 1), abss[j], 0)
                                      for j in range(n_bits)))
                bm[sym] = s

        # ACS: per-state add-compare-select (ties keep predecessor 0).
        # ------------------------------------------------------------
        preds    = _transitions(constraint, polys)
        new_ms   = []
        new_ss   = []
        for s in range(n_states):
            (p0, e0), (p1, e1) = preds[s]
            m0 = Signal(metric_width + 1)
            m1 = Signal(metric_width + 1)
            self.comb += [m0.eq(metrics[p0] + bm[e0]), m1.eq(metrics[p1] + bm[e1])]
            m  = Signal(metric_width + 1)
            sv = Signal(traceback)
            self.comb += If(m1 < m0,
                m.eq(m1), sv.eq(Cat(C(s & 1, 1), survs[p1][:-1])),
            ).Else(
                m.eq(m0), sv.eq(Cat(C(s & 1, 1), survs[p0][:-1])),
            )
            new_ms.append(m)
            new_ss.append(sv)

        # Normalize by the global minimum (also selects the best survivor for the output).
        # --------------------------------------------------------------------------------
        best_m, best_sv = _min_tree([(new_ms[s], new_ss[s]) for s in range(n_states)], self.comb)
        self.sync += If(xfer, *[metrics[s].eq(new_ms[s] - best_m) for s in range(n_states)],
                              *[survs[s].eq(new_ss[s]) for s in range(n_states)])

        # Output.
        # -------
        # Output: the oldest bit of the best path, once the exchange registers are full (the
        # bit for input 0 reaches the survivor MSB on the traceback-th consumed symbol).
        warmup = Signal(max=traceback + 1, reset=traceback - 1)
        self.sync += If(adv,
            self.source.valid.eq(self.sink.valid & (warmup == 0)),
            self.source.data.eq(best_sv[-1]),
            If(xfer & (warmup != 0), warmup.eq(warmup - 1)),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("constraint", size=8,  description="Constraint length K."),
            CSRField("traceback",  size=16, description="Survivor depth (decoding delay)."),
            CSRField("llr_bits",   size=8,  description="Soft-input LLR width (0 = hard-decision input)."),
            CSRField("decision_memory", size=1,
                description="One for folded RAM-survivor traceback; zero for register exchange."),
            CSRField("normalize_interval", size=16,
                description="Accepted symbols between metric normalization cycles."),
            CSRField("cycles_per_output", size=16,
                description="Nominal clocks per decoded output (excludes backpressure)."),
        ])
        self.comb += [
            self._config.fields.constraint.eq(self.constraint),
            self._config.fields.traceback.eq(self.traceback),
            self._config.fields.llr_bits.eq(self.llr_bits or 0),
            self._config.fields.decision_memory.eq(self.decision_memory),
            self._config.fields.normalize_interval.eq(self.normalize_interval),
            self._config.fields.cycles_per_output.eq(self.cycles_per_output),
        ]
