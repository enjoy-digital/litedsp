#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""IIR biquad sections (Direct-Form II Transposed) and cascades, for I/Q streams.

DF2T is chosen for its good fixed-point numerics and minimal state (2 registers/section). The
output and the two state registers are round+saturated each sample for stability. The
feed-forward b·x products are hoisted into a registered intake stage, so the inherent
recursive loop (s -> y -> a·y -> s', which cannot be pipelined across feedback) carries a
single multiply level per cycle. Coefficients come from
``litedsp.filter.design.biquad_sos_quantize`` (Q?.frac_bits).
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, scaled, saturated, add_bypass

# IIR Biquad (single section, complex) -------------------------------------------------------------

@ResetInserter()
class LiteDSPIIRBiquad(LiteXModule):
    """One DF2T biquad section applied to I and Q with shared coefficients.

    ``coefficients`` is a dict ``{b0,b1,b2,a1,a2}`` of signed integers in Q?.``frac_bits``
    (a1,a2 are the *denominator* taps; a0 is normalized to 1).

    ``architecture="classic"`` accepts one sample per clock. ``"folded"`` divides the
    feedback recurrence into feed-forward/y, feedback-product, and state-update cycles. It
    accepts one sample every three clocks, uses two extra cycles of latency, and is
    bit-identical to classic mode. The bypass value is sampled with each folded input.
    """
    def __init__(self, data_width=16, coefficients=None, frac_bits=14,
        architecture="classic", with_csr=True):
        check(architecture in ("classic", "folded"),
            "architecture must be 'classic' or 'folded'.")
        coeffs = coefficients
        if coeffs is None:
            coeffs = {"b0": 1 << frac_bits, "b1": 0, "b2": 0, "a1": 0, "a2": 0}  # Passthrough.
        self.data_width   = data_width
        self.frac_bits    = frac_bits
        self.coefficients = coeffs
        self.state_width = data_width + frac_bits + 4
        self.architecture    = architecture
        self.sample_interval = 1 if architecture == "classic" else 3
        self.latency    = 2 if architecture == "classic" else 4
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Coefficients.
        # -------------
        b0, b1, b2 = coeffs["b0"], coeffs["b1"], coeffs["b2"]
        a1, a2     = coeffs["a1"], coeffs["a2"]
        SW         = self.state_width

        if architecture == "classic":
            # Handshake.
            # ----------
            adv = Signal()
            self.comb += [
                adv.eq(self.source.ready | ~self.source.valid),
                self.sink.ready.eq(adv),
            ]

            # Datapath.
            # ---------
            # The recursive loop s -> y -> a·y -> s' is a single pass per sample by nature;
            # hoist the feed-forward b·x products into a registered intake stage.
            v_px = Signal()
            self.sync += If(adv, v_px.eq(self.sink.valid))
            for field in ["i", "q"]:
                x   = getattr(self.sink, field)
                px0 = Signal((SW, True))
                px1 = Signal((SW, True))
                px2 = Signal((SW, True))
                self.sync += If(adv, px0.eq(b0*x), px1.eq(b1*x), px2.eq(b2*x))

                s1 = Signal((SW, True))
                s2 = Signal((SW, True))
                y  = Signal((data_width, True))
                self.comb += y.eq(scaled(px0 + s1, frac_bits, data_width)[0])
                self.sync += If(adv & v_px,
                    s1.eq(saturated(px1 + s2 - a1*y, SW)),
                    s2.eq(saturated(px2 - a2*y, SW)),
                )
                self.sync += If(adv, getattr(self.source, field).eq(y))

            valid_pipe = Signal(2)
            self.sync += If(adv, valid_pipe.eq(Cat(self.sink.valid, valid_pipe[0])))
            self.comb += self.source.valid.eq(valid_pipe[1])
            add_bypass(self)
        else:
            # Three-clock feedback fold: (1) b*x and y, (2) a*y products, (3) state update.
            # The recurrence boundary is therefore explicit and timing-safe, at the cost of
            # accepting one sample every three clocks.
            self.bypass = Signal()
            phase    = Signal(2)
            advance  = Signal()
            accept   = Signal()
            bypass_r = Signal()
            self.comb += [
                advance.eq(self.source.ready | ~self.source.valid),
                self.sink.ready.eq(((phase == 0) | (phase == 3)) & advance),
                accept.eq(self.sink.valid & self.sink.ready),
            ]
            self.sync += [
                If(self.source.valid & self.source.ready, self.source.valid.eq(0)),
                If(accept, bypass_r.eq(self.bypass), phase.eq(1)),
                If(phase == 1,
                    phase.eq(2),
                ).Elif(phase == 2,
                    phase.eq(3),
                ).Elif((phase == 3) & advance,
                    self.source.valid.eq(1),
                    If(accept, phase.eq(1)).Else(phase.eq(0)),
                ),
            ]
            for field in ["i", "q"]:
                x   = getattr(self.sink, field)
                x_r = Signal((data_width, True))
                px0 = Signal((SW, True))
                px1 = Signal((SW, True))
                px2 = Signal((SW, True))
                s1  = Signal((SW, True))
                s2  = Signal((SW, True))
                y_r = Signal((data_width, True))
                ay1 = Signal((SW, True))
                ay2 = Signal((SW, True))
                self.sync += [
                    If(accept,
                        x_r.eq(x), px0.eq(b0*x), px1.eq(b1*x), px2.eq(b2*x),
                    ),
                    If(phase == 1,
                        y_r.eq(scaled(px0 + s1, frac_bits, data_width)[0]),
                    ),
                    If(phase == 2,
                        ay1.eq(a1*y_r), ay2.eq(a2*y_r),
                    ),
                    If((phase == 3) & advance,
                        If(~bypass_r,
                            s1.eq(saturated(px1 + s2 - ay1, SW)),
                            s2.eq(saturated(px2 - ay2, SW)),
                        ),
                        getattr(self.source, field).eq(Mux(bypass_r, x_r, y_r)),
                    ),
                ]

# IIR Biquad cascade -------------------------------------------------------------------------------

class LiteDSPIIRBiquadCascade(LiteXModule):
    """Cascade of DF2T biquad sections (``sections`` = list of coeff dicts)."""
    def __init__(self, data_width=16, sections=None, frac_bits=14,
        architecture="classic", with_csr=True):
        check(sections, "Provide at least one biquad section.")
        self.sections = []
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        last = self.sink
        for n, sec in enumerate(sections):
            bq = LiteDSPIIRBiquad(data_width=data_width, coefficients=sec,
                frac_bits=frac_bits, architecture=architecture, with_csr=False)
            self.add_module(name=f"section{n}", module=bq)
            self.comb += last.connect(bq.sink)
            self.sections.append(bq)
            last = bq.source
        self.comb += last.connect(self.source)
        self.latency = sum(bq.latency for bq in self.sections)
