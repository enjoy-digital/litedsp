#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Kalman tracker: the shared tracker engine with a constant-velocity Kalman update per axis."""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr import *

from litedsp.common      import check, rounded, saturated
from litedsp.radar.track import _LiteDSPTracker, TRACK_FREE, TRACK_TENTATIVE, TRACK_CONFIRMED

# Kalman Tracker -----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPKalmanTracker(_LiteDSPTracker):
    """Constant-velocity Kalman tracker over ``n_tracks`` slots (same stream contract, association,
    confirmation and emission as :class:`LiteDSPAlphaBetaTracker`).

    Per track and axis the filter keeps the covariance ``P11, P12, P22`` (Q.cov_frac, clamped to
    ``cov_width`` bits with the sticky ``cov_sat``). On the terminator each active track first
    predicts its covariance with the process noise ``q`` (``P11 += 2 P12 + P22 + q/4``,
    ``P12 += P22 + q/2``, ``P22 += q``), then, when assigned, computes the gains
    ``K1 = P11 / (P11 + r)`` and ``K2 = P12 / (P11 + r)`` with bit-serial dividers
    (``cov_width + cov_frac`` cycles, both axes in parallel), updates ``P = pred + K1 e``,
    ``V = V + K2 e`` and the covariance (``P11 (1 - K1)``, ``P12 (1 - K1)``,
    ``P22 - K2 P12``); coasting tracks keep the predicted covariance. New tracks start with
    ``P11 = r``, ``P12 = 0``, ``P22 = p_vel0``. ``q``, ``r`` and ``p_vel0`` are runtime
    (Q.cov_frac, bins^2 and bins^2 per CPI^2); for a tracking index ``lam = sqrt(q / r)`` the
    steady-state gains approach ``alpha_beta_from_index(lam)``.
    """
    def __init__(self, n_tracks=4, index_width=12, frac_bits=4, velocity_frac=8, cov_frac=8,
                 cov_width=24,
        data_width=17, with_csr=True, with_irq=False):
        check(4 <= cov_frac <= 12 and cov_frac < cov_width <= 32,
              "expected 4 <= cov_frac <= 12 < cov_width <= 32")
        self.cov_frac  = cov_frac
        self.cov_width = cov_width
        _LiteDSPTracker.__init__(self, n_tracks=n_tracks, index_width=index_width,
                                 frac_bits=frac_bits,
            velocity_frac=velocity_frac, gain_frac=cov_frac, data_width=data_width,
            with_csr=with_csr,
            with_irq=with_irq)

    def _add_controls(self):
        CF, CW, T = self.cov_frac, self.cov_width, self.n_tracks
        self.q       = Signal(CW, reset=int(round(0.05*(1 << CF))))     # Process noise.
        self.r       = Signal(CW, reset=int(round(0.5*(1 << CF))))      # Measurement noise.
        self.p_vel0  = Signal(CW, reset=int(round(4.0*(1 << CF))))      # Initial velocity variance.
        self.cov_sat = Signal()                                         # Sticky.
        self.clear_sat = Signal()
        # Covariance register file (per track, per axis).
        self._cov = {a: {
            n: [Signal(CW, name=f"{n}_{a}{k}") for k in range(T)] for n in ("P11", "P12", "P22")}
                     for a in ("r", "d")}

    def _new_track_init(self, k):
        cov = self._cov
        return ([NextValue(cov[a]["P11"][k], self.r) for a in ("r", "d")] +
                [NextValue(cov[a]["P12"][k], 0) for a in ("r", "d")] +
                [NextValue(cov[a]["P22"][k], self.p_vel0) for a in ("r", "d")])

    def _add_update_states(self, fsm, c):
        idx, A, PV, VW, T = c["idx"], c["A"], c["PV"], c["VW"], c["T"]
        CF, CW = self.cov_frac, self.cov_width
        P_r, P_d, V_r, V_d, pred_r, pred_d = c["P_r"], c["P_d"], c["V_r"], c["V_d"], c["pred_r"], c[
            "pred_d"]
        hits, misses, state, assigned, hits_inc = c["hits"], c["misses"], c["state"], c[
            "assigned"], c["hits_inc"]
        cov  = self._cov
        covA = {a: {n: Array(cov[a][n]) for n in cov[a]} for a in cov}
        NB, KW = CW + CF, CF + 4                                # Quotient bits; gain width (<= 16).

        # Predicted covariance (registered), innovation covariance, restoring dividers.
        # ----------------------------------------------------------------------------
        p11p, p12p, p22p, S, e = {}, {}, {}, {}, {}
        dv1, dv2, rem1, rem2, q1, q2 = {}, {}, {}, {}, {}, {}
        dstep = Signal(max=NB + 1)
        pred_sums = {}
        for a, (meas, pred) in (("r", (A["meas_r"], A["pred_r"])),
                                ("d", (A["meas_d"], A["pred_d"]))):
            p11p[a], p12p[a], p22p[a] = Signal(CW), Signal(CW), Signal(CW)
            S[a] = Signal(CW + 1)
            e[a] = Signal((PV + 1, True))
            dv1[a], dv2[a]   = Signal(NB), Signal(NB)           # Dividends (shifted out MSB first).
            rem1[a], rem2[a] = Signal(CW + 2), Signal(CW + 2)
            q1[a], q2[a]     = Signal(NB), Signal(NB)
            s11, s12, s22 = Signal(CW + 3), Signal(CW + 3), Signal(CW + 3)
            pred_sums[a] = (s11, s12, s22)
            self.comb += [
                e[a].eq(meas[idx] - pred[idx]),
                S[a].eq(p11p[a] + self.r),
                s11.eq(covA[a]["P11"][idx] + (covA[a]["P12"][idx] << 1) + covA[a]["P22"][idx]
                    + (self.q >> 2)),
                s12.eq(covA[a]["P12"][idx] + covA[a]["P22"][idx] + (self.q >> 1)),
                s22.eq(covA[a]["P22"][idx] + self.q),
            ]
        sat_any = Signal()
        self.comb += sat_any.eq(
            reduce_or([pred_sums[a][i] > (1 << CW) - 1 for a in ("r", "d") for i in range(3)]))
        def clampc(v):                                                  # Clamp to [0, 2^CW - 1].
            return Mux(v > (1 << CW) - 1, (1 << CW) - 1, v[:CW])

        # Post-update quantities (combinational from the gains and the predicted covariance).
        # -----------------------------------------------------------------------------------
        newP, newV, newc = {}, {}, {}
        for a, (V, pred) in (("r", (A["V_r"], A["pred_r"])), ("d", (A["V_d"], A["pred_d"]))):
            k1, k2 = Signal(KW), Signal(KW)
            self.comb += [
                k1.eq(Mux(q1[a] > (1 << KW) - 1, (1 << KW) - 1, q1[a][:KW])),
                k2.eq(Mux(q2[a] > (1 << KW) - 1, (1 << KW) - 1, q2[a][:KW])),
            ]
            k1s, k2s = Signal((KW + 1, True)), Signal((KW + 1, True))
            pk1, pk2 = Signal((PV + KW + 2, True)), Signal((PV + KW + 2, True))
            sumP, sumV = Signal((PV + 2, True)), Signal((VW + 2, True))
            newP[a], newV[a] = Signal((PV, True)), Signal((VW, True))
            one_k1 = Signal((KW + 2, True))
            c11, c12, c22 = [Signal((CW + KW + 3, True), name=f"c{n}_{a}")
                                     for n in ("11", "12", "22")]
            n11, n12, n22 = [Signal((CW + 3, True), name=f"n{n}_{a}") for n in ("11", "12", "22")]
            self.comb += [
                k1s.eq(k1), k2s.eq(k2),
                pk1.eq(e[a]*k1s), pk2.eq(e[a]*k2s),
                sumP.eq(pred[idx] + rounded(pk1, CF)), sumV.eq(V[idx] + rounded(pk2, CF)),
                newP[a].eq(saturated(sumP, PV)), newV[a].eq(saturated(sumV, VW)),
                one_k1.eq((1 << CF) - k1s),
                c11.eq(p11p[a]*one_k1), c12.eq(p12p[a]*one_k1), c22.eq(p12p[a]*k2s),
                n11.eq(rounded(c11, CF)), n12.eq(rounded(c12, CF)),
                n22.eq(p22p[a] - rounded(c22, CF)),
            ]
            newc[a] = tuple(Signal(CW, name=f"newc_{a}{i}") for i in range(3))
            for dst, src in zip(newc[a], (n11, n12, n22)):
                self.comb += dst.eq(
                    Mux(src < 0, 0, Mux(src > (1 << CW) - 1, (1 << CW) - 1, src[:CW])))

        # States: UPDATE (predict covariance) -> KLOAD -> KDIV (gains) -> KAPPLY -> PREDICT.
        # ----------------------------------------------------------------------------------
        fsm.act("UPDATE",
            *[NextValue(p11p[a], clampc(pred_sums[a][0])) for a in ("r", "d")],
            *[NextValue(p12p[a], clampc(pred_sums[a][1])) for a in ("r", "d")],
            *[NextValue(p22p[a], clampc(pred_sums[a][2])) for a in ("r", "d")],
            If(sat_any & (A["state"][idx] != TRACK_FREE), NextValue(self.cov_sat, 1)),
            If((A["state"][idx] != TRACK_FREE) & A["assigned"][idx],
                NextState("KLOAD"),
            ).Else(
                NextState("KAPPLY"),
            ),
        )
        fsm.act("KLOAD",
            NextValue(dstep, 0),
            # p11p << CF.
            *[NextValue(dv1[a], Cat(Replicate(C(0, 1), CF), p11p[a])) for a in ("r", "d")],
            *[NextValue(dv2[a], Cat(Replicate(C(0, 1), CF), p12p[a])) for a in ("r", "d")],
            *[NextValue(rem1[a], 0) for a in ("r", "d")],
            *[NextValue(rem2[a], 0) for a in ("r", "d")],
            *[NextValue(q1[a], 0) for a in ("r", "d")], *[NextValue(q2[a], 0) for a in ("r", "d")],
            NextState("KDIV"),
        )
        div_ops = []
        for a in ("r", "d"):
            for dv, rem, q in ((dv1[a], rem1[a], q1[a]), (dv2[a], rem2[a], q2[a])):
                r2  = Signal(CW + 3)
                bit = Signal()
                self.comb += [r2.eq(Cat(dv[NB - 1], rem)), bit.eq(r2 >= S[a])]
                div_ops += [
                    If(bit, NextValue(rem, (r2 - S[a])[:CW + 2])).Else(NextValue(rem, r2[:CW + 2])),
                    NextValue(q, Cat(bit, q[:NB - 1])),
                    NextValue(dv, Cat(C(0, 1), dv[:NB - 1])),
                ]
        fsm.act("KDIV",
            *div_ops,
            NextValue(dstep, dstep + 1),
            If(dstep == NB - 1, NextState("KAPPLY")),
        )
        fsm.act("KAPPLY",
            *[If(idx == k,
                If(state[k] != TRACK_FREE,
                    If(assigned[k],
                        NextValue(P_r[k], newP["r"]), NextValue(P_d[k], newP["d"]),
                        NextValue(V_r[k], newV["r"]), NextValue(V_d[k], newV["d"]),
                        *[NextValue(cov[a][n][k], newc[a][i]) for a in ("r", "d") for i,
                          n in enumerate(("P11", "P12", "P22"))],
                        NextValue(hits[k], hits_inc), NextValue(misses[k], 0),
                        If((state[k] == TRACK_TENTATIVE) & (hits_inc >= self.confirm_hits),
                            NextValue(state[k], TRACK_CONFIRMED),
                        ),
                    ).Else(
                        NextValue(P_r[k], pred_r[k]), NextValue(P_d[k], pred_d[k]),
                        *[NextValue(cov[a][n][k], (p11p, p12p, p22p)[i][a]) for a in ("r", "d")
                            for i, n in enumerate(("P11", "P12", "P22"))],
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
        self.sync += If(self.clear_sat, self.cov_sat.eq(0))

    def _add_filter_csr(self):
        CW = self.cov_width
        self._noise = CSRStorage(fields=[
            CSRField("q", size=16, offset=0,  reset=self.q.reset.value, description=f"Process noise (Q.{self.cov_frac} bins^2/CPI^2)."),
            CSRField("r", size=16, offset=16, reset=self.r.reset.value, description=f"Measurement noise (Q.{self.cov_frac} bins^2)."),
        ])
        self._p_vel0 = CSRStorage(CW, reset=self.p_vel0.reset.value, name="p_vel0",
                                  description="Initial velocity variance.")
        self._cov = CSRStorage(fields=[
            CSRField("clear_sat", size=1, offset=0, pulse=True, description="Clear the covariance saturation flag."),
        ])
        self._cov_status = CSRStatus(fields=[
            CSRField("cov_sat", size=1, offset=0, description="Sticky: a covariance term saturated."),
        ])
        self.comb += [
            self.q.eq(self._noise.fields.q), self.r.eq(self._noise.fields.r),
            self.p_vel0.eq(self._p_vel0.storage),
            self.clear_sat.eq(self._cov.fields.clear_sat),
            self._cov_status.fields.cov_sat.eq(self.cov_sat),
        ]

def reduce_or(terms):
    out = 0
    for t in terms:
        out = out | t
    return out
