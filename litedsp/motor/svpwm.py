#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common           import check, abc_layout, iq_layout, rounded, saturated
from litedsp.motor.transforms import CONST_FRAC, C_SQ3_2

# Space-Vector PWM Modulator -----------------------------------------------------------------------

@ResetInserter()
class LiteDSPSVPWM(LiteXModule):
    """Space-vector modulator: alpha/beta voltage vector -> three signed phase duties.

    Inverse Clarke (kept two bits wider, one rounding) followed by min/max zero-sequence
    injection ``v0 = -(max + min)/2``, which is the classic SVPWM waveform: the line-to-line
    voltages are unchanged while the linear (unclipped) range extends from a phase peak of
    1.0 to ``2/sqrt(3) = 1.1547`` pu of ``V_dc/2``. ``injection`` (runtime, reset from the
    constructor) selects it (``"minmax"``) or plain sinusoidal modulation (``"none"``); the
    phase duties are saturated to ``+/-1.0`` (over-modulation clamp) and map to 0..100 % in
    :class:`~litedsp.motor.pwm.LiteDSPPWM`. Fixed 3-cycle latency, one multiplier.

    Parameters
    ----------
    injection : str
        Zero-sequence injection at reset: ``"minmax"`` (space vector) or ``"none"``.
    """
    def __init__(self, data_width=16, injection="minmax", with_csr=True):
        check(data_width >= 4, "expected data_width >= 4")
        check(injection in ("minmax", "none"), "expected injection in ('minmax', 'none')")
        self.data_width = data_width
        self.latency    = 3
        self.sink      = stream.Endpoint(iq_layout(data_width))              # (v_alpha, v_beta).
        self.source    = stream.Endpoint(abc_layout(data_width))             # Duties (+/-1.0).
        self.injection = Signal(reset=int(injection == "minmax"))            # Zero-sequence on.

        # # #

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]
        valid_pipe = Signal(3)
        first_pipe = Signal(3)
        last_pipe  = Signal(3)
        inj_pipe   = Signal(2)
        self.sync += If(adv,
            valid_pipe.eq(Cat(self.sink.valid, valid_pipe[:-1])),
            first_pipe.eq(Cat(self.sink.first, first_pipe[:-1])),
            last_pipe.eq(Cat(self.sink.last,   last_pipe[:-1])),
            inj_pipe.eq(Cat(self.injection, inj_pipe[:-1])),
        )
        self.comb += [
            self.source.valid.eq(valid_pipe[-1]),
            self.source.first.eq(first_pipe[-1]),
            self.source.last.eq(last_pipe[-1]),
        ]

        # Stage 1: inverse Clarke at data_width + 2 bits (|v_phase| <= 1.37 pu, one rounding).
        # -----------------------------------------------------------------------------------
        XW      = data_width + 2
        PW      = data_width + CONST_FRAC + 2
        kb_full = Signal((PW, True))
        half_a  = Signal((PW, True))
        b_full  = Signal((PW + 1, True))
        c_full  = Signal((PW + 1, True))
        self.comb += [
            kb_full.eq(self.sink.q*C_SQ3_2),
            half_a.eq(self.sink.i << (CONST_FRAC - 1)),
            b_full.eq(kb_full - half_a),
            c_full.eq(-kb_full - half_a),
        ]
        a1, b1, c1 = Signal((XW, True)), Signal((XW, True)), Signal((XW, True))
        self.sync += If(adv,
            a1.eq(self.sink.i),
            b1.eq(rounded(b_full, CONST_FRAC)),
            c1.eq(rounded(c_full, CONST_FRAC)),
        )

        # Stage 2: zero-sequence v0 = -(max + min)/2 (+ delayed phases).
        # --------------------------------------------------------------
        mx, mn = Signal((XW, True)), Signal((XW, True))
        mx_ab  = Signal((XW, True))
        mn_ab  = Signal((XW, True))
        s_mm   = Signal((XW + 1, True))
        self.comb += [
            mx_ab.eq(Mux(a1 > b1, a1, b1)), mn_ab.eq(Mux(a1 > b1, b1, a1)),
            mx.eq(Mux(mx_ab > c1, mx_ab, c1)), mn.eq(Mux(mn_ab < c1, mn_ab, c1)),
            s_mm.eq(-(mx + mn)),
        ]
        a2, b2, c2, v0 = (Signal((XW, True)) for _ in range(4))
        self.sync += If(adv, a2.eq(a1), b2.eq(b1), c2.eq(c1), v0.eq(rounded(s_mm, 1)))

        # Stage 3: inject (or not) and clamp to +/-1.0.
        # ---------------------------------------------
        v0_sel = Signal((XW, True))
        self.comb += v0_sel.eq(Mux(inj_pipe[-1], v0, 0))
        outs = []
        for x in (a2, b2, c2):
            s = Signal((XW + 1, True))
            self.comb += s.eq(x + v0_sel)
            outs.append(saturated(s, data_width))
        self.sync += If(adv,
            self.source.a.eq(outs[0]),
            self.source.b.eq(outs[1]),
            self.source.c.eq(outs[2]),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("injection", size=1, offset=0, reset=self.injection.reset.value, description="Zero-sequence injection.", values=[
                ("``0b0``", "Sinusoidal modulation (no zero sequence)."),
                ("``0b1``", "Space-vector (min/max zero-sequence injection)."),
            ]),
        ])
        self.comb += self.injection.eq(self._control.fields.injection)
