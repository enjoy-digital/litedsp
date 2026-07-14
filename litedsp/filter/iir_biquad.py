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
    """
    def __init__(self, data_width=16, coefficients=None, frac_bits=14, with_csr=True):
        coeffs = coefficients
        if coeffs is None:
            coeffs = {"b0": 1 << frac_bits, "b1": 0, "b2": 0, "a1": 0, "a2": 0}  # Passthrough.
        self.data_width   = data_width
        self.frac_bits    = frac_bits
        self.coefficients = coeffs
        self.state_width = data_width + frac_bits + 4
        self.latency    = 2                       # Registered b·x intake + recurrence/output.
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Coefficients.
        # -------------
        b0, b1, b2 = coeffs["b0"], coeffs["b1"], coeffs["b2"]
        a1, a2     = coeffs["a1"], coeffs["a2"]
        SW         = self.state_width

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
        ]

        # Datapath.
        # ---------
        # The recursive loop s -> y -> a·y -> s' is a single pass per sample by nature; hoist
        # the feed-forward b·x products into a registered intake stage so only one multiply
        # level remains inside it.
        v_px = Signal()                           # Intake stage holds a real sample.
        self.sync += If(adv, v_px.eq(self.sink.valid))
        for field in ["i", "q"]:
            x   = getattr(self.sink, field)
            px0 = Signal((SW, True))              # Registered b*x products (intake stage).
            px1 = Signal((SW, True))
            px2 = Signal((SW, True))
            self.sync += If(adv, px0.eq(b0*x), px1.eq(b1*x), px2.eq(b2*x))

            s1 = Signal((SW, True))               # DF2T state (Q.frac, saturated on update).
            s2 = Signal((SW, True))
            y  = Signal((data_width, True))
            self.comb += y.eq(scaled(px0 + s1, frac_bits, data_width)[0])  # y = b0*x + s1, back to Q1.(N-1).
            # State advances only when the intake holds a real sample (v_px), so pipeline
            # bubbles cannot corrupt the recursion.
            self.sync += If(adv & v_px,
                s1.eq(saturated(px1 + s2 - a1*y, SW)),
                s2.eq(saturated(px2 - a2*y, SW)),
            )
            self.sync += If(adv, getattr(self.source, field).eq(y))

        # Valid Pipeline.
        # ---------------
        valid_pipe = Signal(2)                    # Matches intake + output register stages.
        self.sync += If(adv, valid_pipe.eq(Cat(self.sink.valid, valid_pipe[0])))
        self.comb += self.source.valid.eq(valid_pipe[1])

        # Bypass.
        # -------
        add_bypass(self)

# IIR Biquad cascade -------------------------------------------------------------------------------

class LiteDSPIIRBiquadCascade(LiteXModule):
    """Cascade of DF2T biquad sections (``sections`` = list of coeff dicts)."""
    def __init__(self, data_width=16, sections=None, frac_bits=14, with_csr=True):
        check(sections, "Provide at least one biquad section.")
        self.sections = []
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        last = self.sink
        for n, sec in enumerate(sections):
            bq = LiteDSPIIRBiquad(data_width=data_width, coefficients=sec, frac_bits=frac_bits, with_csr=False)
            self.add_module(name=f"section{n}", module=bq)
            self.comb += last.connect(bq.sink)
            self.sections.append(bq)
            last = bq.source
        self.comb += last.connect(self.source)
        self.latency = sum(bq.latency for bq in self.sections)
