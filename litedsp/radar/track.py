#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Multi-target tracking on per-CPI target bursts: gated nearest-neighbour association and
alpha-beta filtering per track."""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourcePulse
from litex.soc.interconnect                  import stream

from litedsp.common import check, target_layout, track_layout, rounded, saturated

TRACK_FREE, TRACK_TENTATIVE, TRACK_CONFIRMED = 0, 1, 2

# Alpha-Beta Tracker -------------------------------------------------------------------------------

class _LiteDSPTracker(LiteXModule):
    """Shared tracker engine: register file, serial gated nearest-neighbour association, the
    per-CPI update loop (the filter update itself comes from ``_add_update_states``), track
    confirmation / coasting / deletion and the framed track burst. See
    :class:`LiteDSPAlphaBetaTracker` for the stream contract.

    Each incoming record (:func:`~litedsp.common.target_layout`) is associated serially with
    the active, not yet assigned track whose prediction lies within the gates
    (``|dr| <= gate_r`` and ``|dd| <= gate_d``) with the lowest ``|dr| + |dd|`` (lowest index on
    ties); an unassociated record initialises the lowest free slot (tentative, velocity 0) or is
    dropped when none is free (``n_tracks + 2`` cycles per record, input stalled). The terminator
    updates every active track: assigned tracks filter ``P = pred + alpha*e``,
    ``V = V + beta*e`` (gains unsigned Q1.gain_frac, positions Q.velocity_frac bins, velocities
    Q.velocity_frac bins per CPI), count a hit and confirm at ``confirm_hits``; unassigned
    tracks coast on their prediction and are freed after ``max_misses`` consecutive misses;
    then ``pred = P + V``. The confirmed tracks (and the tentative ones with ``emit_tentative``)
    are emitted as a :func:`~litedsp.common.track_layout` burst closed by a terminator whose
    ``hits`` field is the active track count; ``ev.update`` fires with it.
    ``latency = None``; rate data dependent.
    """
    def _new_track_init(self, k):                                   # Extra per-slot initialisation.
        return []

    def __init__(self, n_tracks=4, index_width=12, frac_bits=4, velocity_frac=8, gain_frac=8,
        data_width=17, with_csr=True, with_irq=False):
        check(1 <= n_tracks <= 16, "expected 1 <= n_tracks <= 16")
        check(1 <= frac_bits <= velocity_frac <= 12, "expected 1 <= frac_bits <= velocity_frac <= 12")
        check(1 <= gain_frac <= 12, "expected 1 <= gain_frac <= 12")
        self.n_tracks      = n_tracks
        self.index_width   = index_width
        self.frac_bits     = frac_bits
        self.velocity_frac = velocity_frac
        self.gain_frac     = gain_frac
        self.data_width    = data_width
        self.latency       = None
        self.sink   = stream.Endpoint(target_layout(data_width, index_width, frac_bits))
        self.source = stream.Endpoint(track_layout(index_width, frac_bits, velocity_frac, n_tracks))
        F, VF, GF = frac_bits, velocity_frac, gain_frac
        PW  = index_width + F                                           # Stream positions.
        PV  = index_width + VF + 2                                      # Internal positions (signed).
        VW  = index_width + VF                                          # Velocities (signed).
        self._add_controls()
        self.gate_r         = Signal(PW, reset=2 << F)                  # Q.frac bins.
        self.gate_d         = Signal(PW, reset=2 << F)
        self.confirm_hits   = Signal(4, reset=3)
        self.max_misses     = Signal(4, reset=2)
        self.emit_tentative = Signal()
        self.clear          = Signal()
        self.active         = Signal(max=n_tracks + 1)                  # Active tracks after the update.
        self.confirmed      = Signal(max=n_tracks + 1)
        self.dropped        = Signal(32)
        self.cpi_count      = Signal(32)
        self.cpi_done       = Signal()

        # # #

        T  = n_tracks
        IW = max(1, (T - 1).bit_length())

        # Track register file (explicit per-slot signals; writes are decoded, never Array-indexed).
        # ------------------------------------------------------------------------------------------
        def regs(name, shape):
            return [Signal(shape, name=f"{name}{k}") for k in range(T)]
        P_r, P_d       = regs("P_r", (PV, True)), regs("P_d", (PV, True))
        pred_r, pred_d = regs("pred_r", (PV, True)), regs("pred_d", (PV, True))
        V_r, V_d       = regs("V_r", (VW, True)), regs("V_d", (VW, True))
        meas_r, meas_d = regs("meas_r", (PV, True)), regs("meas_d", (PV, True))
        assigned       = regs("assigned", 1)
        hits           = regs("hits", 4)
        misses         = regs("misses", 4)
        state          = regs("state", 2)
        A = {n: Array(v) for n, v in (("P_r", P_r), ("P_d", P_d), ("pred_r", pred_r), ("pred_d", pred_d),
             ("V_r", V_r), ("V_d", V_d), ("meas_r", meas_r), ("meas_d", meas_d), ("assigned", assigned),
             ("hits", hits), ("misses", misses), ("state", state))}
        idx  = Signal(max=max(T, 2))
        last_idx = (idx == T - 1)
        def write(name, value, index=None):                             # Decoded register write.
            index = idx if index is None else index
            regs_ = {"P_r": P_r, "P_d": P_d, "pred_r": pred_r, "pred_d": pred_d, "V_r": V_r, "V_d": V_d,
                     "meas_r": meas_r, "meas_d": meas_d, "assigned": assigned, "hits": hits,
                     "misses": misses, "state": state}[name]
            return [If(index == k, regs_[k].eq(value)) for k in range(T)]

        # Incoming record (Q.frac -> Q.velocity_frac) and association scores.
        # -------------------------------------------------------------------
        mr, md = Signal((PV, True)), Signal((PV, True))
        gr, gd = Signal((PV, True)), Signal((PV, True))
        mr_u, md_u, gr_u, gd_u = [Signal(PV, name=n) for n in ("mr_u", "md_u", "gr_u", "gd_u")]   # Explicit
        self.comb += [                                                                             # shift widths.
            mr_u.eq(self.sink.range << (VF - F)), md_u.eq(self.sink.doppler << (VF - F)),
            gr_u.eq(self.gate_r << (VF - F)),     gd_u.eq(self.gate_d << (VF - F)),
            gr.eq(gr_u), gd.eq(gd_u),
        ]
        dr, dd   = Signal((PV + 1, True)), Signal((PV + 1, True))
        adr, add = Signal(PV + 1), Signal(PV + 1)
        score    = Signal(PV + 2)
        in_gate  = Signal()
        cand     = Signal()
        best     = Signal(max=max(T, 2))
        best_v   = Signal()
        best_s   = Signal(PV + 2)
        self.comb += [
            dr.eq(mr - A["pred_r"][idx]), dd.eq(md - A["pred_d"][idx]),
            adr.eq(Mux(dr < 0, -dr, dr)), add.eq(Mux(dd < 0, -dd, dd)),
            score.eq(adr + add),
            in_gate.eq((adr <= gr) & (add <= gd)),
            cand.eq((A["state"][idx] != TRACK_FREE) & ~A["assigned"][idx] & in_gate & (~best_v | (score < best_s))),
        ]
        free_any = Signal()
        free_idx = Signal(max=max(T, 2))
        self.comb += free_any.eq(0)
        for k in reversed(range(T)):                                    # Lowest free slot wins.
            self.comb += If(state[k] == TRACK_FREE, free_any.eq(1), free_idx.eq(k))

        predsum_r, predsum_d = Signal((PV + 1, True)), Signal((PV + 1, True))
        self.comb += [predsum_r.eq(A["P_r"][idx] + A["V_r"][idx]), predsum_d.eq(A["P_d"][idx] + A["V_d"][idx])]
        hits_inc = Signal(4)
        self.comb += hits_inc.eq(Mux(A["hits"][idx] == 15, 15, A["hits"][idx] + 1))

        # Sequencer.
        # ----------
        adv = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        rec_a, term_a = Signal(), Signal()
        n_emitted = Signal(max=T + 1)
        emit_ok = Signal()
        self.comb += emit_ok.eq((A["state"][idx] == TRACK_CONFIRMED) | (self.emit_tentative & (A["state"][idx] == TRACK_TENTATIVE)))
        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                NextValue(idx, 0),
                If(self.sink.hit,
                    NextValue(mr, mr_u),
                    NextValue(md, md_u),
                    NextValue(best_v, 0),
                    NextState("ASSOC"),
                ).Else(
                    NextState("UPDATE"),
                ),
            ),
        )
        fsm.act("ASSOC",
            If(cand,
                NextValue(best, idx), NextValue(best_v, 1), NextValue(best_s, score),
            ),
            NextValue(idx, idx + 1),
            If(last_idx, NextState("ASSIGN")),
        )
        fsm.act("ASSIGN",
            If(best_v,
                *[If(best == k, NextValue(meas_r[k], mr), NextValue(meas_d[k], md), NextValue(assigned[k], 1)) for k in range(T)],
            ).Elif(free_any,
                *[If(free_idx == k,
                    NextValue(P_r[k], mr), NextValue(P_d[k], md), NextValue(pred_r[k], mr), NextValue(pred_d[k], md),
                    NextValue(meas_r[k], mr), NextValue(meas_d[k], md), NextValue(V_r[k], 0), NextValue(V_d[k], 0),
                    NextValue(assigned[k], 1), NextValue(hits[k], 0), NextValue(misses[k], 0),   # The update counts the hit.
                    NextValue(state[k], TRACK_TENTATIVE),
                    *self._new_track_init(k),
                ) for k in range(T)],
            ).Else(
                NextValue(self.dropped, self.dropped + 1),
            ),
            NextState("IDLE"),
        )
        # Filter update states (subclass): entered as "UPDATE" for track idx, leave to "PREDICT".
        ctx = dict(idx=idx, last_idx=last_idx, A=A, P_r=P_r, P_d=P_d, pred_r=pred_r, pred_d=pred_d, V_r=V_r, V_d=V_d,
                   meas_r=meas_r, meas_d=meas_d, assigned=assigned, hits=hits, misses=misses, state=state,
                   hits_inc=hits_inc, PV=PV, VW=VW, T=T)
        self._add_update_states(fsm, ctx)
        fsm.act("PREDICT",
            *[If(idx == k,
                NextValue(pred_r[k], saturated(predsum_r, PV)), NextValue(pred_d[k], saturated(predsum_d, PV)),
            ) for k in range(T)],
            If(last_idx,
                NextValue(idx, 0), NextValue(n_emitted, 0),
                NextState("COUNT"),
            ).Else(
                NextValue(idx, idx + 1),
                NextState("UPDATE"),
            ),
        )
        n_active, n_conf = Signal(max=T + 1), Signal(max=T + 1)
        self.comb += [
            n_active.eq(sum([(s != TRACK_FREE) for s in state])),
            n_conf.eq(sum([(s == TRACK_CONFIRMED) for s in state])),
        ]
        fsm.act("COUNT",
            NextValue(self.active, n_active), NextValue(self.confirmed, n_conf),
            NextState("EMIT"),
        )
        fsm.act("EMIT",
            If(emit_ok,
                rec_a.eq(1),
                If(adv,
                    NextValue(n_emitted, n_emitted + 1),
                    NextValue(idx, idx + 1),
                    If(last_idx, NextState("TERM")),
                ),
            ).Else(
                NextValue(idx, idx + 1),
                If(last_idx, NextState("TERM")),
            ),
        )
        fsm.act("TERM",
            term_a.eq(1),
            If(adv,
                NextValue(self.cpi_count, self.cpi_count + 1),
                NextState("IDLE"),
            ),
        )
        self.sync += If(self.clear, *[state[k].eq(TRACK_FREE) for k in range(T)])

        # Output register.
        # ----------------
        out_r, out_d = Signal((PV, True)), Signal((PV, True))
        outc_r, outc_d = Signal(PW), Signal(PW)
        self.comb += [
            out_r.eq(rounded(A["P_r"][idx], VF - F)), out_d.eq(rounded(A["P_d"][idx], VF - F)),
            outc_r.eq(Mux(out_r < 0, 0, Mux(out_r > (1 << PW) - 1, (1 << PW) - 1, out_r[:PW]))),
            outc_d.eq(Mux(out_d < 0, 0, Mux(out_d > (1 << PW) - 1, (1 << PW) - 1, out_d[:PW]))),
        ]
        self.sync += [
            self.cpi_done.eq(0),
            If(adv,
                self.source.valid.eq(rec_a | term_a),
                self.source.hit.eq(rec_a),
                self.source.first.eq(n_emitted == 0),
                self.source.last.eq(term_a),
                If(rec_a,
                    self.source.range.eq(outc_r), self.source.doppler.eq(outc_d),
                    self.source.velocity.eq(A["V_r"][idx]),
                    self.source.id.eq(idx), self.source.hits.eq(A["hits"][idx]),
                ),
                If(term_a,
                    self.source.range.eq(0), self.source.doppler.eq(0), self.source.velocity.eq(0),
                    self.source.id.eq(0), self.source.hits.eq(self.active),
                    self.cpi_done.eq(1),
                ),
            ),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_csr(self):
        GF, PW = self.gain_frac, self.index_width + self.frac_bits
        self._add_filter_csr()
        self._gates = CSRStorage(fields=[
            CSRField("range",   size=PW, offset=0,  reset=self.gate_r.reset.value, description=f"Range gate (Q.{self.frac_bits} bins)."),
            CSRField("doppler", size=PW, offset=16, reset=self.gate_d.reset.value, description=f"Doppler gate (Q.{self.frac_bits} bins)."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("confirm_hits",   size=4, offset=0, reset=3, description="Hits to confirm a track."),
            CSRField("max_misses",     size=4, offset=4, reset=2, description="Consecutive misses before a track is freed."),
            CSRField("emit_tentative", size=1, offset=8, description="Also emit tentative tracks."),
            CSRField("clear",          size=1, offset=9, pulse=True, description="Free every track."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("active",    size=5, offset=0, description="Active tracks after the last update."),
            CSRField("confirmed", size=5, offset=8, description="Confirmed tracks after the last update."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_tracks",      size=5, offset=0,  description="Track slots."),
            CSRField("frac_bits",     size=4, offset=8,  description="Sub-bin fractional bits."),
            CSRField("velocity_frac", size=4, offset=12, description="Velocity fractional bits."),
            CSRField("gain_frac",     size=4, offset=16, description="Gain fractional bits."),
        ])
        self._dropped   = CSRStatus(32, name="dropped", description="Records dropped (no free slot).")
        self._cpi_count = CSRStatus(32, name="cpi_count", description="Updates since reset.")
        self.comb += [
            self.gate_r.eq(self._gates.fields.range), self.gate_d.eq(self._gates.fields.doppler),
            self.confirm_hits.eq(self._control.fields.confirm_hits),
            self.max_misses.eq(self._control.fields.max_misses),
            self.emit_tentative.eq(self._control.fields.emit_tentative),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.active.eq(self.active), self._status.fields.confirmed.eq(self.confirmed),
            self._config.fields.n_tracks.eq(self.n_tracks), self._config.fields.frac_bits.eq(self.frac_bits),
            self._config.fields.velocity_frac.eq(self.velocity_frac), self._config.fields.gain_frac.eq(self.gain_frac),
            self._dropped.status.eq(self.dropped), self._cpi_count.status.eq(self.cpi_count),
        ]

    def add_irq(self):
        self.ev        = EventManager()
        self.ev.update = EventSourcePulse(description="The tracks were updated (terminator emitted).")
        self.ev.finalize()
        self.comb += self.ev.update.trigger.eq(self.cpi_done)

# Alpha-Beta Tracker -------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPAlphaBetaTracker(_LiteDSPTracker):
    """Alpha-beta tracker over ``n_tracks`` slots fed by per-CPI target bursts.

    Each incoming record (:func:`~litedsp.common.target_layout`) is associated serially with
    the active, not yet assigned track whose prediction lies within the gates
    (``|dr| <= gate_r`` and ``|dd| <= gate_d``) with the lowest ``|dr| + |dd|`` (lowest index on
    ties); an unassociated record initialises the lowest free slot (tentative, velocity 0) or is
    dropped when none is free (``n_tracks + 2`` cycles per record, input stalled). The terminator
    updates every active track: assigned tracks filter ``P = pred + alpha*e``,
    ``V = V + beta*e`` (gains unsigned Q1.gain_frac, positions Q.velocity_frac bins, velocities
    Q.velocity_frac bins per CPI), count a hit and confirm at ``confirm_hits``; unassigned
    tracks coast on their prediction and are freed after ``max_misses`` consecutive misses;
    then ``pred = P + V``. The confirmed tracks (and the tentative ones with ``emit_tentative``)
    are emitted as a :func:`~litedsp.common.track_layout` burst closed by a terminator whose
    ``hits`` field is the active track count; ``ev.update`` fires with it.
    ``latency = None``; rate data dependent.
    """
    def _new_track_init(self, k):
        return []

    def _add_controls(self):
        GF = self.gain_frac
        self.alpha = Signal(GF + 1, reset=int(round(0.5*(1 << GF))))
        self.beta  = Signal(GF + 1, reset=int(round(0.15*(1 << GF))))

    def _add_update_states(self, fsm, c):
        idx, A, PV, VW, GF, T = c["idx"], c["A"], c["PV"], c["VW"], self.gain_frac, c["T"]
        P_r, P_d, V_r, V_d, pred_r, pred_d = c["P_r"], c["P_d"], c["V_r"], c["V_d"], c["pred_r"], c["pred_d"]
        hits, misses, state, assigned, hits_inc = c["hits"], c["misses"], c["state"], c["assigned"], c["hits_inc"]
        # One track per two cycles: products, then apply.
        # -------------------------------------------------
        e_r, e_d = Signal((PV + 1, True)), Signal((PV + 1, True))
        pa_r, pa_d = Signal((PV + 1 + GF + 2, True)), Signal((PV + 1 + GF + 2, True))
        pb_r, pb_d = Signal((PV + 1 + GF + 2, True)), Signal((PV + 1 + GF + 2, True))
        alpha_s, beta_s = Signal((GF + 2, True)), Signal((GF + 2, True))
        self.comb += [
            alpha_s.eq(self.alpha), beta_s.eq(self.beta),
            e_r.eq(A["meas_r"][idx] - A["pred_r"][idx]),
            e_d.eq(A["meas_d"][idx] - A["pred_d"][idx]),
        ]
        self.sync += [
            pa_r.eq(e_r*alpha_s), pa_d.eq(e_d*alpha_s),
            pb_r.eq(e_r*beta_s),  pb_d.eq(e_d*beta_s),
        ]
        newP_r, newP_d = Signal((PV, True)), Signal((PV, True))
        newV_r, newV_d = Signal((VW, True)), Signal((VW, True))
        sumP_r, sumP_d = Signal((PV + 2, True)), Signal((PV + 2, True))
        sumV_r, sumV_d = Signal((VW + 2, True)), Signal((VW + 2, True))
        self.comb += [
            sumP_r.eq(A["pred_r"][idx] + rounded(pa_r, GF)), sumP_d.eq(A["pred_d"][idx] + rounded(pa_d, GF)),
            sumV_r.eq(A["V_r"][idx] + rounded(pb_r, GF)),    sumV_d.eq(A["V_d"][idx] + rounded(pb_d, GF)),
            newP_r.eq(saturated(sumP_r, PV)), newP_d.eq(saturated(sumP_d, PV)),
            newV_r.eq(saturated(sumV_r, VW)), newV_d.eq(saturated(sumV_d, VW)),
        ]
        fsm.act("UPDATE",                                               # Products register this cycle.
            NextState("UPDATE_APPLY"),
        )
        fsm.act("UPDATE_APPLY",
            *[If(idx == k,
                If(state[k] != TRACK_FREE,
                    If(assigned[k],
                        NextValue(P_r[k], newP_r), NextValue(P_d[k], newP_d),
                        NextValue(V_r[k], newV_r), NextValue(V_d[k], newV_d),
                        NextValue(hits[k], hits_inc), NextValue(misses[k], 0),
                        If((state[k] == TRACK_TENTATIVE) & (hits_inc >= self.confirm_hits),
                            NextValue(state[k], TRACK_CONFIRMED),
                        ),
                    ).Else(
                        NextValue(P_r[k], pred_r[k]), NextValue(P_d[k], pred_d[k]),
                        NextValue(misses[k], misses[k] + 1),
                        If(misses[k] + 1 > self.max_misses,
                            NextValue(state[k], TRACK_FREE),
                        ),
                    ),
                ),
                NextValue(assigned[k], 0),
            ) for k in range(T)],
            NextState("PREDICT"),
        )

    def _add_filter_csr(self):
        GF = self.gain_frac
        self._gains = CSRStorage(fields=[
            CSRField("alpha", size=GF + 1, offset=0,  reset=self.alpha.reset.value, description=f"Position gain (Q1.{GF})."),
            CSRField("beta",  size=GF + 1, offset=16, reset=self.beta.reset.value,  description=f"Velocity gain (Q1.{GF})."),
        ])
        self.comb += [self.alpha.eq(self._gains.fields.alpha), self.beta.eq(self._gains.fields.beta)]
