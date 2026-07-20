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

    Adaptation is *delayed LMS* (the standard hardware form). ``architecture="classic"``
    applies the previous sample's registered error/window. ``"pipelined"`` registers the FIR
    products, sum, modulus square, and selected error separately and applies it after four
    accepted samples. Both retain one-sample-per-clock filter throughput; the latter adds two
    output cycles and trades adaptation-loop delay and registers for shorter FIR/CMA cones.

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
    architecture : str
        ``"classic"`` for one-sample delayed LMS, or ``"pipelined"`` for a four-sample
        adaptation delay with unchanged filter throughput and two additional output cycles.
    """
    def __init__(self, n_taps=5, data_width=16, wfrac=14, wint=4, mu_shift=20, cma_egain=0,
        architecture="classic", with_csr=True):
        check(n_taps >= 1, "expected n_taps >= 1")
        check(0 <= cma_egain <= data_width - 1, "expected 0 <= cma_egain <= data_width - 1")
        check(architecture in ("classic", "pipelined"),
            "architecture must be 'classic' or 'pipelined'.")
        self.n_taps   = n_taps
        self.mu_shift = mu_shift                         # LMS step size: mu = 2**-mu_shift.
        self.architecture     = architecture
        self.adaptation_delay = 1 if architecture == "classic" else 4
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
        self.latency  = 1 if architecture == "classic" else 3

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

        # Complex FIR: y = sum w_k * x_k (balanced adder trees). The pipelined architecture
        # registers each complex product before the tree and carries the sample metadata with
        # it; this adds one filter-output cycle without reducing throughput.
        if architecture == "classic":
            yi_full = _adder_tree([wr[k]*xr[k] - wi[k]*xi[k] for k in range(n_taps)])
            yq_full = _adder_tree([wr[k]*xi[k] + wi[k]*xr[k] for k in range(n_taps)])
            fir_valid = self.sink.valid
        else:
            term_width = ww + data_width + 1
            fir_i_terms = [Signal((term_width, True)) for _ in range(n_taps)]
            fir_q_terms = [Signal((term_width, True)) for _ in range(n_taps)]
            fir_valid = Signal()
            fir_d_i, fir_d_q = Signal((data_width, True)), Signal((data_width, True))
            fir_mode = Signal(2)
            fir_r2   = Signal(data_width + 1)
            fir_ddl  = Signal(data_width - 1)
            fir_xr = [Signal((data_width, True)) for _ in range(n_taps)]
            fir_xi = [Signal((data_width, True)) for _ in range(n_taps)]
            self.sync += If(adv,
                fir_valid.eq(self.sink.valid),
                If(self.sink.valid,
                    *[fir_i_terms[k].eq(wr[k]*xr[k] - wi[k]*xi[k]) for k in range(n_taps)],
                    *[fir_q_terms[k].eq(wr[k]*xi[k] + wi[k]*xr[k]) for k in range(n_taps)],
                    fir_d_i.eq(self.sink.d_i), fir_d_q.eq(self.sink.d_q),
                    fir_mode.eq(self.mode), fir_r2.eq(self.cma_r2), fir_ddl.eq(self.dd_level),
                    *[fir_xr[k].eq(xr[k]) for k in range(n_taps)],
                    *[fir_xi[k].eq(xi[k]) for k in range(n_taps)],
                ),
            )
            sum_width = term_width + (n_taps - 1).bit_length()
            sum_i, sum_q = Signal((sum_width, True)), Signal((sum_width, True))
            sum_valid = Signal()
            sum_d_i, sum_d_q = Signal((data_width, True)), Signal((data_width, True))
            sum_mode = Signal(2)
            sum_r2   = Signal(data_width + 1)
            sum_ddl  = Signal(data_width - 1)
            sum_xr = [Signal((data_width, True)) for _ in range(n_taps)]
            sum_xi = [Signal((data_width, True)) for _ in range(n_taps)]
            self.sync += If(adv,
                sum_valid.eq(fir_valid),
                If(fir_valid,
                    sum_i.eq(_adder_tree(fir_i_terms)),
                    sum_q.eq(_adder_tree(fir_q_terms)),
                    sum_d_i.eq(fir_d_i), sum_d_q.eq(fir_d_q),
                    sum_mode.eq(fir_mode), sum_r2.eq(fir_r2), sum_ddl.eq(fir_ddl),
                    *[sum_xr[k].eq(fir_xr[k]) for k in range(n_taps)],
                    *[sum_xi[k].eq(fir_xi[k]) for k in range(n_taps)],
                ),
            )
            yi_full = sum_i
            yq_full = sum_q
            fir_valid = sum_valid
            fir_d_i, fir_d_q = sum_d_i, sum_d_q
            fir_mode, fir_r2, fir_ddl = sum_mode, sum_r2, sum_ddl
            fir_xr, fir_xi = sum_xr, sum_xi
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
        # LMS Update.
        # -----------
        ei_d = Signal((data_width + 1, True))            # Registered error Re{e} (1 growth bit).
        eq_d = Signal((data_width + 1, True))            # Registered error Im{e}.
        xr_d = [Signal((data_width, True)) for _ in range(n_taps)]
        xi_d = [Signal((data_width, True)) for _ in range(n_taps)]
        if architecture == "classic":
            e_i = Signal((data_width + 1, True))
            e_q = Signal((data_width + 1, True))
            m2  = Signal((data_width + 2, True))
            dm  = Signal((data_width + 2, True))
            self.comb += [
                m2.eq(rounded(yi*yi + yq*yq, F)),
                dm.eq(self.cma_r2 - m2),
            ]
            self.comb += Case(self.mode, {
                MODE_CMA: [
                    e_i.eq(scaled(yi*dm, F - cma_egain, data_width + 1)[0]),
                    e_q.eq(scaled(yq*dm, F - cma_egain, data_width + 1)[0]),
                ],
                MODE_DD: [
                    e_i.eq(Mux(yi < 0, -self.dd_level, self.dd_level) - yi),
                    e_q.eq(Mux(yq < 0, -self.dd_level, self.dd_level) - yq),
                ],
                "default": [
                    e_i.eq(self.sink.d_i - yi),
                    e_q.eq(self.sink.d_q - yq),
                ],
            })
            v_update = Signal()
            self.sync += If(xfer,
                ei_d.eq(e_i), eq_d.eq(e_q),
                *[xr_d[k].eq(xr[k]) for k in range(n_taps)],
                *[xi_d[k].eq(xi[k]) for k in range(n_taps)],
                v_update.eq(1),
            )
            update_step = xfer & v_update
            update_ei, update_eq = ei_d, eq_d
            update_xr, update_xi = xr_d, xi_d
        else:
            # The product and sum registers above are the first adaptation stages. Register
            # |y|^2, then the selected error; updates remain four accepted samples behind.
            v1 = Signal()
            yi1, yq1 = Signal((data_width, True)), Signal((data_width, True))
            di1, dq1 = Signal((data_width, True)), Signal((data_width, True))
            mode1 = Signal(2)
            r21 = Signal(data_width + 1)
            ddl1 = Signal(data_width - 1)
            m2_1 = Signal((data_width + 2, True))
            dm_1 = Signal((data_width + 2, True))
            ep_i = Signal((data_width + 1, True))
            ep_q = Signal((data_width + 1, True))
            xr1 = [Signal((data_width, True)) for _ in range(n_taps)]
            xi1 = [Signal((data_width, True)) for _ in range(n_taps)]
            adapt_step = Signal()
            self.comb += adapt_step.eq(fir_valid & adv)
            self.comb += dm_1.eq(r21 - m2_1)
            self.comb += Case(mode1, {
                MODE_CMA: [
                    ep_i.eq(scaled(yi1*dm_1, F - cma_egain, data_width + 1)[0]),
                    ep_q.eq(scaled(yq1*dm_1, F - cma_egain, data_width + 1)[0]),
                ],
                MODE_DD: [
                    ep_i.eq(Mux(yi1 < 0, -ddl1, ddl1) - yi1),
                    ep_q.eq(Mux(yq1 < 0, -ddl1, ddl1) - yq1),
                ],
                "default": [ep_i.eq(di1 - yi1), ep_q.eq(dq1 - yq1)],
            })
            self.sync += If(adapt_step,
                v1.eq(1),
                yi1.eq(yi), yq1.eq(yq), di1.eq(fir_d_i), dq1.eq(fir_d_q),
                mode1.eq(fir_mode), r21.eq(fir_r2), ddl1.eq(fir_ddl),
                m2_1.eq(rounded(yi*yi + yq*yq, F)),
                *[xr1[k].eq(fir_xr[k]) for k in range(n_taps)],
                *[xi1[k].eq(fir_xi[k]) for k in range(n_taps)],
            )

            # Completed errors can arrive while the input has a bubble (the last FIR product
            # is still draining). Keep them in a four-entry queue, but do not consume the head
            # until four newer samples have been accepted. Merely consuming the head on the
            # next input works at full rate but shortens the delayed-LMS distance when a bubble
            # lets an error finish early. Four entries cover all warm-up errors if the input
            # pauses immediately before the first update becomes due.
            update_count = Signal(max=5)
            accepted_count = Signal(max=5)
            update_ei = [Signal((data_width + 1, True)) for _ in range(4)]
            update_eq = [Signal((data_width + 1, True)) for _ in range(4)]
            update_xr = [[Signal((data_width, True)) for _ in range(n_taps)] for _ in range(4)]
            update_xi = [[Signal((data_width, True)) for _ in range(n_taps)] for _ in range(4)]
            error_ready = Signal()
            update_step = Signal()
            self.comb += [
                error_ready.eq(adapt_step & v1),
                update_step.eq(xfer & (accepted_count == 4)),
            ]
            self.sync += If(xfer & (accepted_count != 4),
                accepted_count.eq(accepted_count + 1),
            )
            push0 = [
                update_ei[0].eq(ep_i), update_eq[0].eq(ep_q),
                *[update_xr[0][k].eq(xr1[k]) for k in range(n_taps)],
                *[update_xi[0][k].eq(xi1[k]) for k in range(n_taps)],
            ]
            push1 = [
                update_ei[1].eq(ep_i), update_eq[1].eq(ep_q),
                *[update_xr[1][k].eq(xr1[k]) for k in range(n_taps)],
                *[update_xi[1][k].eq(xi1[k]) for k in range(n_taps)],
            ]
            push2 = [
                update_ei[2].eq(ep_i), update_eq[2].eq(ep_q),
                *[update_xr[2][k].eq(xr1[k]) for k in range(n_taps)],
                *[update_xi[2][k].eq(xi1[k]) for k in range(n_taps)],
            ]
            push3 = [
                update_ei[3].eq(ep_i), update_eq[3].eq(ep_q),
                *[update_xr[3][k].eq(xr1[k]) for k in range(n_taps)],
                *[update_xi[3][k].eq(xi1[k]) for k in range(n_taps)],
            ]
            shift_down = [
                update_ei[0].eq(update_ei[1]), update_eq[0].eq(update_eq[1]),
                *[update_xr[0][k].eq(update_xr[1][k]) for k in range(n_taps)],
                *[update_xi[0][k].eq(update_xi[1][k]) for k in range(n_taps)],
                update_ei[1].eq(update_ei[2]), update_eq[1].eq(update_eq[2]),
                *[update_xr[1][k].eq(update_xr[2][k]) for k in range(n_taps)],
                *[update_xi[1][k].eq(update_xi[2][k]) for k in range(n_taps)],
                update_ei[2].eq(update_ei[3]), update_eq[2].eq(update_eq[3]),
                *[update_xr[2][k].eq(update_xr[3][k]) for k in range(n_taps)],
                *[update_xi[2][k].eq(update_xi[3][k]) for k in range(n_taps)],
            ]
            self.sync += Case(Cat(update_step, error_ready), {
                0b01: [
                    If(update_count >= 2, *shift_down),
                    update_count.eq(update_count - 1),
                ],
                0b10: [
                    If(update_count == 0, *push0, update_count.eq(1)).
                    Elif(update_count == 1, *push1, update_count.eq(2)).
                    Elif(update_count == 2, *push2, update_count.eq(3)).
                    Elif(update_count == 3, *push3, update_count.eq(4)),
                ],
                0b11: [
                    If(update_count == 1, *push0).
                    Elif(update_count == 2,
                        update_ei[0].eq(update_ei[1]), update_eq[0].eq(update_eq[1]),
                        *[update_xr[0][k].eq(update_xr[1][k]) for k in range(n_taps)],
                        *[update_xi[0][k].eq(update_xi[1][k]) for k in range(n_taps)],
                        *push1,
                    ).Elif(update_count == 3,
                        update_ei[0].eq(update_ei[1]), update_eq[0].eq(update_eq[1]),
                        *[update_xr[0][k].eq(update_xr[1][k]) for k in range(n_taps)],
                        *[update_xi[0][k].eq(update_xi[1][k]) for k in range(n_taps)],
                        update_ei[1].eq(update_ei[2]), update_eq[1].eq(update_eq[2]),
                        *[update_xr[1][k].eq(update_xr[2][k]) for k in range(n_taps)],
                        *[update_xi[1][k].eq(update_xi[2][k]) for k in range(n_taps)],
                        *push2,
                    ).Elif(update_count == 4,
                        *shift_down,
                        *push3,
                    ),
                ],
            })
            update_ei, update_eq = update_ei[0], update_eq[0]
            update_xr, update_xi = update_xr[0], update_xi[0]
        for k in range(n_taps):
            self.sync += If(update_step & self.train,
                wr[k].eq(saturated(wr[k] + ((update_ei*update_xr[k] + update_eq*update_xi[k]) >> mu_shift), ww)),
                wi[k].eq(saturated(wi[k] + ((update_eq*update_xr[k] - update_ei*update_xi[k]) >> mu_shift), ww)),
            )

        # Output.
        # -------
        self.sync += If(adv,
            self.source.i.eq(yi),
            self.source.q.eq(yq),
            self.source.valid.eq(fir_valid),
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
