#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, saturated, scaled

# Mueller & Muller Symbol Timing Recovery ----------------------------------------------------------

@ResetInserter()
class TimingRecovery(LiteXModule):
    """Symbol timing recovery with an interpolation controller (M&M or Gardner detector).

    Maintains a samples-per-symbol estimate ``omega`` and a fractional interpolation phase
    ``mu``. Each symbol: interpolate (cubic Farrow) at ``mu``, form the timing error, update
    ``omega += g_omega·e`` (clamped) and ``mu += omega + g_mu·e``, then advance the input by
    ``floor(mu)`` samples (the integer sample-slip) keeping the fractional part. Input is
    nominally ``sps`` samples/symbol; output is one (timing-aligned) sample per symbol.

    Detectors (``ted``): ``"mm"`` — Mueller & Muller, decision-directed
    (``e = Re{slice(prev)·conj(y) − slice(y)·conj(prev)}``, multiplier-free); ``"gardner"`` —
    non-decision-aided (``e = Re{(y − y_prev)·conj(y_mid)}`` with a second interpolation at
    the symbol midpoint; modulation-agnostic, locks without carrier lock, for ``sps=2``).
    """
    def __init__(self, data_width=16, sps=2, frac=16, gain_mu=0.1, gain_omega=None, ted="mm",
        with_csr=True):
        assert ted in ("mm", "gardner")
        if gain_omega is None:
            gain_omega = gain_mu*gain_mu/4
        self.data_width = data_width
        self.sps = sps
        self.ted = ted
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        ONE       = 1 << frac
        gm_q      = int(round(gain_mu*ONE))
        go_q      = int(round(gain_omega*ONE))
        amp_shift = data_width - 1
        omega_mid = sps*ONE
        omega_lim = int(round(0.05*sps*ONE))
        iw        = frac + 4                              # mu/omega width (a few integer bits).

        # State. Gardner keeps one extra window sample for the midpoint interpolation.
        nw    = 4 if ted == "mm" else 5
        need  = Signal(4, reset=nw)                      # Inputs to consume before next output.
        mu    = Signal(iw, reset=ONE//2)
        omega = Signal((iw, True), reset=omega_mid)
        wr    = [Signal((data_width, True)) for _ in range(nw)]  # Input window (wr[-1] = newest).
        wi    = [Signal((data_width, True)) for _ in range(nw)]
        last_r, last_q = Signal((data_width, True)), Signal((data_width, True))

        consuming = Signal()
        emitting  = Signal()
        self.comb += [
            consuming.eq(need != 0),
            emitting.eq(need == 0),
            self.sink.ready.eq(consuming),
            self.source.valid.eq(emitting),
        ]

        # Cubic (Catmull-Rom) interpolation at mu (fractional part) between wr[1], wr[2].
        mu_f = mu[:frac]
        def interp(w):
            a0 = w[1]
            a1 = Signal((data_width + 2, True)); a2 = Signal((data_width + 4, True)); a3 = Signal((data_width + 4, True))
            self.comb += [
                a1.eq((w[2] - w[0]) >> 1),
                a2.eq((2*w[0] - 5*w[1] + 4*w[2] - w[3]) >> 1),
                a3.eq((-w[0] + 3*w[1] - 3*w[2] + w[3]) >> 1),
            ]
            y2 = Signal((data_width + 6, True)); y1 = Signal((data_width + 6, True))
            self.comb += [y2.eq(a2 + ((mu_f*a3) >> frac)), y1.eq(a1 + ((mu_f*y2) >> frac))]
            return scaled(a0*ONE + mu_f*y1, frac, data_width)[0]
        yr = Signal((data_width, True)); yq = Signal((data_width, True))
        self.comb += [yr.eq(interp(wr[nw-4:])), yq.eq(interp(wi[nw-4:]))]
        self.comb += [self.source.i.eq(yr), self.source.q.eq(yq)]

        err = Signal((data_width + 3, True))
        if ted == "mm":
            # M&M timing error (slices are +/-1, so no multiplies): e = sgn(last)·y − sgn(y)·last.
            def sgnmul(sign_src, val):
                return Mux(sign_src >= 0, val, -val)
            self.comb += err.eq(sgnmul(last_r, yr) + sgnmul(last_q, yq)
                              - sgnmul(yr, last_r) - sgnmul(yq, last_q))
        else:
            # Gardner: e = Re{(y_prev − y)·conj(y_mid)}, midpoint interpolated one sample back
            # (half a symbol at sps=2, same fractional phase). The error is only valid when the
            # controller stepped the nominal sps samples — on a slip the T−1 point is not the
            # half-symbol point, and feeding that error back makes the loop hunt.
            ymid_r = Signal((data_width, True)); ymid_q = Signal((data_width, True))
            self.comb += [ymid_r.eq(interp(wr[:4])), ymid_q.eq(interp(wi[:4]))]
            g       = Signal((2*data_width + 2, True))
            gs      = Signal((data_width + 8, True))
            nominal = Signal()
            self.comb += [
                g.eq((last_r - yr)*ymid_r + (last_q - yq)*ymid_q),   # Sign matches the mu += g·e loop.
                # Rescale toward the M&M error amplitude (the product is quadratic in the
                # signal, so the raw >> (dw-1) form is an order of magnitude weaker).
                gs.eq(g >> (data_width - 5)),
                err.eq(Mux(nominal, saturated(gs, data_width + 3), 0)),
            ]

        # Loop update + interpolation controller (on each emitted symbol).
        omega_n = Signal((iw, True))
        mu_n    = Signal((iw + 1, True))
        self.comb += [
            omega_n.eq(omega + ((go_q*err) >> amp_shift)),
            mu_n.eq(mu + omega + ((gm_q*err) >> amp_shift)),
        ]
        omega_c = Signal((iw, True))
        self.comb += omega_c.eq(
            Mux(omega_n < (omega_mid - omega_lim), omega_mid - omega_lim,
            Mux(omega_n > (omega_mid + omega_lim), omega_mid + omega_lim, omega_n)))
        step = Signal(4)
        self.comb += step.eq(Mux(mu_n[frac:] == 0, 1, mu_n[frac:]))   # floor(mu), at least 1.
        if ted == "gardner":
            self.sync += If(emitting & self.source.ready, nominal.eq(step == sps))

        self.sync += [
            If(consuming & self.sink.valid,                # Slide the window in one sample.
                *[wr[k].eq(wr[k + 1]) for k in range(nw - 1)], wr[nw - 1].eq(self.sink.i),
                *[wi[k].eq(wi[k + 1]) for k in range(nw - 1)], wi[nw - 1].eq(self.sink.q),
                need.eq(need - 1),
            ),
            If(emitting & self.source.ready,              # Emit a symbol, run the loop.
                last_r.eq(yr), last_q.eq(yq),
                omega.eq(omega_c),
                mu.eq(mu_n[:frac]),                        # Keep the fractional part.
                need.eq(step),
            ),
        ]

        if with_csr:
            self._omega = CSRStatus(iw, name="omega", description="Samples/symbol estimate (Q.frac).")
            self.comb += self._omega.status.eq(omega)
