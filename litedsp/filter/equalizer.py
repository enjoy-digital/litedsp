#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common     import check, iq_layout, rounded, scaled, saturated
from litedsp.filter.fir import _adder_tree

# Adaptation modes (runtime ``mode`` control / CSR field).
MODE_TRAINED = 0  # e = d - y (external reference: training sequence or slicer feedback).
MODE_CMA     = 1  # e = y * (R2 - |y|^2) (blind, constant-modulus; R2 from ``cma_r2``).
MODE_DD      = 2  # e = slice(y) - y (decision-directed: nearest QPSK point at ``dd_level``).

# Complex LMS Equalizer ----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPLMSEqualizer(LiteXModule):
    """Adaptive complex FIR equalizer: trained LMS, blind CMA or decision-directed.

    Filters ``x`` with ``n_taps`` complex weights and adapts them with the stochastic-gradient
    update ``w_k += mu * e * conj(x[n-k])``, where the error ``e`` is selected by the runtime
    ``mode`` control (``MODE_*``, CSR field of the same values):

    - ``0`` trained (default): ``e = d - y``. The sink carries both the input (``i``,``q``)
      and the desired symbol (``d_i``,``d_q``) — a training sequence, or an external slicer's
      decisions fed back as ``d``.
    - ``1`` CMA (blind, no reference): ``e = y * (R2 - |y|^2)`` minimizes the constant-modulus
      dispersion ``E[(|y|^2 - R2)^2]``; ``d_i``/``d_q`` are ignored. ``cma_r2`` holds the
      target modulus R2 in the Q-format of ``|y|^2`` rescaled to the sample fractional bits
      (see the error-term section for the derivation): for QPSK at per-axis amplitude ``A``,
      program ``cma_r2 = round(2*A**2 / 2**(data_width-1))``. The per-axis error is saturated
      to the trained-mode error width *before* the ``mu`` shift, bounding the worst-case
      weight step during acquisition (critical for CMA stability).
    - ``2`` decision-directed: ``d`` is the nearest QPSK point of ``y``, i.e.
      ``(sign(y_i), sign(y_q)) * dd_level``, and ``e = d - y``; use after blind (CMA)
      acquisition to track with lower misadjustment. ``dd_level`` is the positive per-axis
      decision amplitude.

    Drive ``train`` low to freeze adaptation in any mode (weights hold, filtering continues).
    ``mu_shift`` sets the (inverse) step size; weights are Q.``wfrac`` with the center tap
    initialized to 1.0.

    Adaptation is *delayed LMS* (the standard hardware form): the update applies the previous
    sample's error (registered with its input-window snapshot), so the filter and the update
    each carry one multiply level per cycle instead of chaining y -> e -> update
    combinationally. Convergence is indistinguishable at practical step sizes. (The CMA error
    itself adds two multiply levels — ``|y|^2`` then ``y * dm`` — in front of the error
    register; pipeline externally or lower the clock if that path limits timing.)

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
    cma_egain : int
        Log2 gain applied to the CMA error before its saturation, e = sat(y * dm *
        2**cma_egain) with dm the modulus error R2 - mag(y)^2; other modes are unaffected.
        The CMA gradient scales as signal power times amplitude, so at operating levels well
        below full scale it is much smaller than the trained/DD error (~30x at 0.2 of full
        scale): set cma_egain so both land at a comparable magnitude and a single mu_shift
        serves blind acquisition and decision-directed tracking (each unit doubles the
        effective CMA step). 0 keeps the exact derived Q-format.
    """
    def __init__(self, n_taps=5, data_width=16, wfrac=14, wint=4, mu_shift=20, cma_egain=0,
        with_csr=True):
        check(n_taps >= 1, "expected n_taps >= 1")
        check(0 <= cma_egain <= data_width - 1, "expected 0 <= cma_egain <= data_width - 1")
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
        self.train    = Signal(reset=1)                  # Enable weight adaptation (freeze when 0).
        self.mode     = Signal(2, reset=MODE_TRAINED)    # Error-term select (MODE_*).
        self.cma_r2   = Signal(data_width + 1)           # CMA target modulus R2 (frac = data_width - 1).
        self.dd_level = Signal(data_width - 1)           # DD per-axis decision amplitude (positive).
        self.latency  = 1

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

        # Error Term.
        # -----------
        # Mode-selected adaptation error e, in the sample Q-format with one growth bit
        # (data_width + 1 signed) — exactly what the trained-mode e = d - y occupies, so the
        # LMS update below consumes it unchanged in every mode.
        #
        # CMA scaling (samples Q1.F with F = data_width - 1 fractional bits):
        #   |y|^2 = yi^2 + yq^2                  frac 2F, 2W bits unsigned (2W + 1 signed);
        #   m2    = round(|y|^2 / 2^F)           frac F, <= 2^W       -> W + 2 bits signed;
        #   dm    = R2 - m2                      frac F (R2 = cma_r2) -> W + 2 bits signed;
        #   e     = sat(round(yi_q * dm / 2^(F - cma_egain)))  frac F, saturated to W + 1 bits.
        # With cma_egain = 0 this is the exact frac-F CMA error; cma_egain boosts it toward
        # the trained-error magnitude (see the class docstring). Saturating e *before* the mu
        # shift bounds the worst-case weight step during blind acquisition (large-modulus
        # transients make |dm| ~ 2^W), which is what keeps CMA stable at practical step sizes.
        F   = data_width - 1                             # Sample fractional bits (Q1.F).
        e_i = Signal((data_width + 1, True))             # Selected error Re{e}.
        e_q = Signal((data_width + 1, True))             # Selected error Im{e}.
        m2  = Signal((data_width + 2, True))             # |y|^2 rescaled to frac F.
        dm  = Signal((data_width + 2, True))             # Modulus error R2 - |y|^2 (frac F).
        self.comb += [
            m2.eq(rounded(yi*yi + yq*yq, F)),
            dm.eq(self.cma_r2 - m2),
        ]
        self.comb += Case(self.mode, {
            MODE_CMA: [                                  # Blind: e = y * (R2 - |y|^2).
                e_i.eq(scaled(yi*dm, F - cma_egain, data_width + 1)[0]),
                e_q.eq(scaled(yq*dm, F - cma_egain, data_width + 1)[0]),
            ],
            MODE_DD: [                                   # Decision-directed: e = slice(y) - y.
                e_i.eq(Mux(yi < 0, -self.dd_level, self.dd_level) - yi),
                e_q.eq(Mux(yq < 0, -self.dd_level, self.dd_level) - yq),
            ],
            "default": [                                 # Trained (0, and reserved 3): e = d - y.
                e_i.eq(self.sink.d_i - yi),
                e_q.eq(self.sink.d_q - yq),
            ],
        })

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
            ei_d.eq(e_i),
            eq_d.eq(e_q),
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
            self._train = CSRStorage(1, reset=1, name="train",
                description="Enable weight adaptation (0 = freeze: weights hold, filtering continues).")
            self._control = CSRStorage(fields=[
                CSRField("mode", size=2, reset=MODE_TRAINED, values=[
                    ("0", "trained"), ("1", "cma"), ("2", "dd")],
                    description="Error-term select (3 reserved, behaves as trained)."),
            ])
            self._cma_r2 = CSRStorage(data_width + 1, name="cma_r2",
                description="CMA target modulus R2, fractional bits = data_width - 1 "
                            "(QPSK at per-axis amplitude A: round(2*A**2 / 2**(data_width-1))).")
            self._dd_level = CSRStorage(data_width - 1, name="dd_level",
                description="Decision-directed per-axis QPSK decision amplitude (positive).")
            self.comb += [
                self.train.eq(self._train.storage),
                self.mode.eq(self._control.fields.mode),
                self.cma_r2.eq(self._cma_r2.storage),
                self.dd_level.eq(self._dd_level.storage),
            ]
