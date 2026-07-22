#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, saturated, scaled

# Mueller & Muller Symbol Timing Recovery ----------------------------------------------------------

@ResetInserter()
class LiteDSPTimingRecovery(LiteXModule):
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

    Parameters
    ----------
    sps : int
        Nominal input samples per symbol; ``omega`` starts here and is clamped to
        sps +/- 5%. The Gardner detector assumes sps = 2.
    gain_mu : float
        Proportional gain on the fractional interpolation phase ``mu`` (quantized to
        Q.frac). Larger = faster timing acquisition, more jitter.
    gain_omega : float
        Integral gain on the samples/symbol estimate ``omega`` (quantized to Q.frac;
        default gain_mu**2/4, the critically-damped choice).
    ted : str
        Timing error detector: "mm" (Mueller & Muller, decision-directed, multiplier-free)
        or "gardner" (non-decision-aided, extra midpoint interpolation, needs sps = 2).
    architecture : str
        ``"classic"`` updates the loop directly from the registered timing error.
        ``"pipelined"`` registers the scaled proportional/integral corrections first,
        adding one processing clock per output symbol while shortening the feedback path.
    """
    def __init__(self, data_width=16, sps=2, frac=16, gain_mu=0.1, gain_omega=None, ted="mm",
        with_csr=True, architecture="classic"):
        check(ted in ("mm", "gardner"), "expected ted in ('mm', 'gardner')")
        check(architecture in ("classic", "pipelined"),
            "architecture must be 'classic' or 'pipelined'.")
        if gain_omega is None:
            gain_omega = gain_mu*gain_mu/4
        self.data_width = data_width
        self.sps = sps
        self.ted = ted
        self.architecture = architecture
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.latency = None  # Variable (adaptive symbol-rate output).

        # # #

        # Constants.
        # ----------
        ONE       = 1 << frac                             # 1.0 in Q.frac fixed-point.
        gm_q      = int(round(gain_mu*ONE))               # Loop gains quantized to Q.frac.
        go_q      = int(round(gain_omega*ONE))
        amp_shift = data_width - 1                        # Normalizes a full-scale error to ~1.0.
        omega_mid = sps*ONE                               # Nominal samples/symbol (Q.frac).
        omega_lim = int(round(0.05*sps*ONE))              # Clamp omega to nominal +/-5%.
        iw        = frac + 4                              # mu/omega width (a few integer bits).

        # Signals.
        # --------
        # State. Gardner keeps one extra window sample for the midpoint interpolation.
        nw    = 4 if ted == "mm" else 5
        need  = Signal(4, reset=nw)                      # Inputs to consume before next output.
        mu    = Signal(iw, reset=ONE//2)
        omega = Signal((iw, True), reset=omega_mid)
        wr    = [Signal((data_width, True)) for _ in range(nw)]  # Input window (wr[-1] = newest).
        wi    = [Signal((data_width, True)) for _ in range(nw)]
        last_r, last_q = Signal((data_width, True)), Signal((data_width, True))

        # Handshake.
        # ----------
        # The interpolator registers below are free-running and settle iteratively once the
        # window/mu stop changing; emission waits SETTLE cycles after the last consumed sample
        # so only one multiply level remains per clock (was: three chained multiplies, the
        # block's critical path). Throughput cost: sps + SETTLE cycles per symbol.
        # The loop-pipelined form spends one otherwise idle controller clock registering the
        # gain-scaled corrections.  Timing recovery already accepts fewer than one sample per
        # clock, so this makes the timing/throughput trade-off explicit without reducing the
        # datapath's accepted-sample rate while it is consuming a window.
        loop_pipeline = int(architecture == "pipelined")
        SETTLE = 5 + loop_pipeline                       # Interpolator/error + optional loop cut.
        self.settle_cycles = SETTLE
        settle    = Signal(max=SETTLE + 1)
        consuming = Signal()
        emitting  = Signal()
        self.comb += [
            consuming.eq(need != 0),
            emitting.eq((need == 0) & (settle == SETTLE)),
            self.sink.ready.eq(consuming),
            self.source.valid.eq(emitting),
        ]
        self.sync += [
            If(consuming,
                settle.eq(0),
            ).Elif(settle != SETTLE,
                settle.eq(settle + 1),
            ),
        ]

        # Interpolator.
        # -------------
        # Cubic (Catmull-Rom) interpolation at mu (fractional part) between wr[1], wr[2],
        # registered per multiply stage (valid SETTLE cycles after window/mu are stable).
        mu_f = mu[:frac]
        def interp(w):
            a0 = w[1]
            a1 = Signal((data_width + 2, True)); a2 = Signal((data_width + 4, True)); a3 = Signal((data_width + 4, True))
            self.comb += [
                a1.eq((w[2] - w[0]) >> 1),
                a2.eq((2*w[0] - 5*w[1] + 4*w[2] - w[3]) >> 1),
                a3.eq((-w[0] + 3*w[1] - 3*w[2] + w[3]) >> 1),
            ]
            a0_r = Signal((data_width, True))
            a1_r = Signal((data_width + 2, True))
            a2_r = Signal((data_width + 4, True))
            a3_r = Signal((data_width + 4, True))
            y2 = Signal((data_width + 6, True)); y1 = Signal((data_width + 6, True))
            y  = Signal((data_width, True))
            self.sync += [
                a0_r.eq(a0), a1_r.eq(a1), a2_r.eq(a2), a3_r.eq(a3),
                y2.eq(a2_r + ((mu_f*a3_r) >> frac)),
                y1.eq(a1_r + ((mu_f*y2) >> frac)),
                y.eq(scaled(a0_r*ONE + mu_f*y1, frac, data_width)[0]),
            ]
            return y
        yr = interp(wr[nw-4:])
        yq = interp(wi[nw-4:])
        self.comb += [self.source.i.eq(yr), self.source.q.eq(yq)]

        # Timing Error.
        # -------------
        err = Signal((data_width + 3, True))             # Registered (the 4th settle stage).
        if ted == "mm":
            # M&M timing error (slices are +/-1, so no multiplies): e = sgn(last)·y − sgn(y)·last.
            def sgnmul(sign_src, val):
                return Mux(sign_src >= 0, val, -val)
            self.sync += err.eq(sgnmul(last_r, yr) + sgnmul(last_q, yq)
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
            ]
            self.sync += err.eq(Mux(nominal, saturated(gs, data_width + 3), 0))

        # Loop update + interpolation controller (on each emitted symbol).
        # ----------------------------------------------------------------
        omega_n = Signal((iw, True))
        mu_n    = Signal((iw + 1, True))
        if architecture == "classic":
            self.comb += [
                omega_n.eq(omega + ((go_q*err) >> amp_shift)),
                mu_n.eq(mu + omega + ((gm_q*err) >> amp_shift)),
            ]
        else:
            omega_correction = Signal((iw, True))
            mu_correction    = Signal((iw + 1, True))
            self.sync += [
                omega_correction.eq((go_q*err) >> amp_shift),
                mu_correction.eq((gm_q*err) >> amp_shift),
            ]
            self.comb += [
                omega_n.eq(omega + omega_correction),
                mu_n.eq(mu + omega + mu_correction),
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

        # CSR.
        # ----
        if with_csr:
            self._omega = CSRStatus(iw, name="omega", description="Samples/symbol estimate (Q.frac).")
            self.comb += self._omega.status.eq(omega)
