#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled

# Arbitrary-Ratio Resampler ------------------------------------------------------------------------

@ResetInserter()
class LiteDSPArbResampler(LiteXModule):
    """Arbitrary (non-rational) sample-rate conversion via cubic Farrow + a phase accumulator.

    ``ratio = f_in / f_out`` (Q.``frac``): each output advances the fractional phase by ``ratio``;
    whenever the integer part rolls over, one input sample is consumed (window shifts). The
    output is a Catmull-Rom interpolation at the fractional phase. ``ratio < 1`` interpolates,
    ``> 1`` decimates (precede with an anti-alias filter when decimating).

    Parameters
    ----------
    ratio_int_bits : int
        Integer bits of the ratio/phase registers (total width = frac + ratio_int_bits);
        bounds the maximum decimation ratio f_in/f_out at just under 2**ratio_int_bits.
    """
    def __init__(self, data_width=16, frac=15, ratio_int_bits=8, with_csr=True):
        self.frac = frac
        ONE = 1 << frac
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.ratio  = Signal(frac + ratio_int_bits, reset=ONE)   # f_in/f_out, Q.frac.
        self.latency = None  # Variable (fractional-phase resampling).

        # # #

        # Control.
        # --------
        phase  = Signal(frac + ratio_int_bits)  # Q(ratio_int_bits).frac position; integer part = inputs owed.
        primed = Signal()                  # 4-sample interpolation window is filled.
        cnt    = Signal(3)                 # Priming counter (stops at 4).
        self.comb += primed.eq(cnt >= 4)

        # Consume inputs while the integer phase is nonzero (window must slide) or while priming.
        consuming = Signal()
        self.comb += consuming.eq((phase[frac:] != 0) | ~primed)
        # Consume and emit are mutually exclusive, so the window is stable when sampled.
        self.comb += [
            self.sink.ready.eq(consuming),
            self.source.valid.eq(primed & ~consuming),
        ]
        mu = phase[:frac]                  # Fractional position in [x0, x1), Q.frac.

        # Datapath.
        # ---------
        for f in ["i", "q"]:
            xin = getattr(self.sink, f)
            xm1, x0, x1, x2 = (Signal((data_width, True)) for _ in range(4))  # Window (xm1 oldest); bracket [x0, x1].
            self.sync += If(self.sink.valid & consuming, xm1.eq(x0), x0.eq(x1), x1.eq(x2), x2.eq(xin))
            # Catmull-Rom coefficients (all multiples of 1/2, so shifts only).
            a1 = Signal((data_width + 2, True))
            a2 = Signal((data_width + 4, True))
            a3 = Signal((data_width + 4, True))
            self.comb += [
                a1.eq((x1 - xm1) >> 1),
                a2.eq((2*xm1 - 5*x0 + 4*x1 - x2) >> 1),
                a3.eq((-xm1 + 3*x0 - 3*x1 + x2) >> 1),
            ]
            # Horner evaluation: y = x0 + mu*(a1 + mu*(a2 + mu*a3)), all combinational.
            y2 = Signal((data_width + 6, True))
            y1 = Signal((data_width + 6, True))
            self.comb += [
                y2.eq(a2 + ((mu*a3) >> frac)),
                y1.eq(a1 + ((mu*y2) >> frac)),
            ]
            self.comb += getattr(self.source, f).eq(scaled(x0*(1 << frac) + mu*y1, frac, data_width)[0])

        # Phase Accumulator.
        # ------------------
        # The two branches are exclusive (source.valid implies ~consuming): consuming one input
        # retires one integer step; producing one output advances the phase by ratio.
        self.sync += [
            If(self.sink.valid & consuming,
                If(cnt < 4, cnt.eq(cnt + 1)),
                If(phase[frac:] != 0, phase.eq(phase - ONE)),
            ),
            If(self.source.valid & self.source.ready,
                phase.eq(phase + self.ratio),
            ),
        ]

        # CSR.
        # ----
        if with_csr:
            self._ratio = CSRStorage(frac + ratio_int_bits, reset=ONE, name="ratio",
                description="Resampling ratio f_in/f_out (Q.frac).")
            self.comb += self.ratio.eq(self._ratio.storage)
