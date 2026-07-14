#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common     import check, iq_layout, scaled, saturated
from litedsp.filter.fir import _adder_tree

# Complex LMS Equalizer ----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPLMSEqualizer(LiteXModule):
    """Adaptive complex FIR equalizer (LMS), trained or decision-directed.

    Filters ``x`` with ``n_taps`` complex weights and adapts them to minimize ``|d - y|``:
    ``w_k += mu * e * conj(x[n-k])`` with ``e = d - y``. The sink carries both the input
    (``i``,``q``) and the desired symbol (``d_i``,``d_q``); drive ``train`` low to freeze the
    weights (feed a slicer's decision back as ``d`` for decision-directed operation). ``mu_shift``
    sets the (inverse) step size; weights are Q.``wfrac`` with the center tap initialized to 1.0.

    Adaptation is *delayed LMS* (the standard hardware form): the update applies the previous
    sample's error (registered with its input-window snapshot), so the filter and the update
    each carry one multiply level per cycle instead of chaining y -> e -> update
    combinationally. Convergence is indistinguishable at practical step sizes.

    Parameters
    ----------
    wfrac : int
        Fractional bits of each complex weight (signed Q``wint``.``wfrac``); the center tap is
        initialized to 1.0 = 2**wfrac. More bits = finer adaptation steps.
    wint : int
        Integer bits of each weight; bounds the weight magnitude (updates saturate). Keep
        wint + wfrac <= 18 so each weight*sample product fits one 18x18 DSP block.
    mu_shift : int
        LMS step-size exponent, mu = 2**-mu_shift (update uses a bare right shift). Larger =
        slower but more stable convergence with lower steady-state misadjustment.
    """
    def __init__(self, n_taps=5, data_width=16, wfrac=14, wint=4, mu_shift=20, with_csr=True):
        check(n_taps >= 1, "expected n_taps >= 1")
        self.n_taps   = n_taps
        self.mu_shift = mu_shift                         # LMS step size: mu = 2**-mu_shift.
        # Weight = Q``wint``.``wfrac`` signed. ``wint`` integer bits bound the weight magnitude
        # (saturated below); keeping ww = wint + wfrac <= 18 makes each weight*sample a single
        # 18x18 DSP. Stable equalizers have O(1) weights, so a few integer bits suffice.
        ww = wint + wfrac                                # Weight register width.
        self.sink = stream.Endpoint([
            ("i", (data_width, True)), ("q", (data_width, True)),
            ("d_i", (data_width, True)), ("d_q", (data_width, True)),
        ])
        self.source = stream.Endpoint(iq_layout(data_width))
        self.train   = Signal(reset=1)                   # Enable weight adaptation (freeze when 0).
        self.latency = 1

        # # #

        # Handshake.
        # ----------
        adv  = Signal()                                  # Output slot free or being consumed.
        xfer = Signal()                                  # A sample (+ desired symbol) is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Input Shift Register.
        # ---------------------
        # Input shift register: tap 0 = current sample, taps 1.. = history.
        regs_r = [Signal((data_width, True)) for _ in range(n_taps - 1)]
        regs_i = [Signal((data_width, True)) for _ in range(n_taps - 1)]
        xr = [self.sink.i] + regs_r
        xi = [self.sink.q] + regs_i
        if n_taps > 1:
            self.sync += If(xfer,
                regs_r[0].eq(self.sink.i), regs_i[0].eq(self.sink.q),
                *[regs_r[k].eq(regs_r[k-1]) for k in range(1, n_taps - 1)],
                *[regs_i[k].eq(regs_i[k-1]) for k in range(1, n_taps - 1)],
            )

        # Complex FIR.
        # ------------
        wr = [Signal((ww, True)) for _ in range(n_taps)]
        wi = [Signal((ww, True)) for _ in range(n_taps)]
        wr[n_taps//2].reset = 1 << wfrac                 # Center tap = 1.0.

        # Complex FIR: y = sum w_k * x_k (balanced adder trees).
        yi_full = _adder_tree([wr[k]*xr[k] - wi[k]*xi[k] for k in range(n_taps)])
        yq_full = _adder_tree([wr[k]*xi[k] + wi[k]*xr[k] for k in range(n_taps)])
        yi = scaled(yi_full, wfrac, data_width)[0]
        yq = scaled(yq_full, wfrac, data_width)[0]

        # LMS Update.
        # -----------
        # Delayed-LMS update: register the error with its input-window snapshot, apply it on
        # the next accepted sample: w_k += mu * e[n-1] * conj(x[n-1-k]).
        ei_d = Signal((data_width + 1, True))            # Registered error Re{e} (1 growth bit).
        eq_d = Signal((data_width + 1, True))            # Registered error Im{e}.
        xr_d = [Signal((data_width, True)) for _ in range(n_taps)]
        xi_d = [Signal((data_width, True)) for _ in range(n_taps)]
        v_e  = Signal()                                  # A registered error is pending.
        self.sync += If(xfer,
            ei_d.eq(self.sink.d_i - yi),
            eq_d.eq(self.sink.d_q - yq),
            *[xr_d[k].eq(xr[k]) for k in range(n_taps)],
            *[xi_d[k].eq(xi[k]) for k in range(n_taps)],
            v_e.eq(1),
        )
        for k in range(n_taps):
            self.sync += If(xfer & self.train & v_e,
                wr[k].eq(saturated(wr[k] + ((ei_d*xr_d[k] + eq_d*xi_d[k]) >> mu_shift), ww)),
                wi[k].eq(saturated(wi[k] + ((eq_d*xr_d[k] - ei_d*xi_d[k]) >> mu_shift), ww)),
            )

        # Output.
        # -------
        self.sync += If(adv,
            self.source.i.eq(yi),
            self.source.q.eq(yq),
            self.source.valid.eq(self.sink.valid),
        )

        # CSR.
        # ----
        if with_csr:
            self._train = CSRStorage(1, reset=1, name="train", description="Enable LMS adaptation.")
            self.comb += self.train.eq(self._train.storage)
