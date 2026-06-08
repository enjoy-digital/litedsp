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

# Farrow Fractional Interpolator -------------------------------------------------------------------

@ResetInserter()
class FarrowInterpolator(LiteXModule):
    """Cubic (Catmull-Rom) Farrow fractional-delay interpolator with runtime ``mu``.

    Interpolates between samples at fractional position ``mu`` (Q.``frac_bits``, 0..1) using a
    4-tap window via Horner evaluation. The Catmull-Rom coefficients are all multiples of 1/2,
    so no awkward divides are needed. One output per input (a fractional delay); pair with a
    phase accumulator for arbitrary-ratio resampling.
    """
    def __init__(self, data_width=16, frac_bits=15, with_csr=True):
        self.data_width = data_width
        self.frac_bits  = frac_bits
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.mu     = Signal(frac_bits)          # Fractional position in [0, 1).

        # # #

        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]
        mu = Signal((frac_bits + 1, True))
        self.comb += mu.eq(self.mu)

        for field in ["i", "q"]:
            xin = getattr(self.sink, field)
            xm1 = Signal((data_width, True))     # x[n-3] .. x[n] window (xm1 oldest).
            x0  = Signal((data_width, True))
            x1  = Signal((data_width, True))
            x2  = Signal((data_width, True))
            self.sync += If(xfer, xm1.eq(x0), x0.eq(x1), x1.eq(x2), x2.eq(xin))

            # Catmull-Rom Farrow coefficients (window p0..p3 = xm1, x0, x1, x2; bracket x0..x1).
            a0 = x0
            a1 = Signal((data_width + 2, True))
            a2 = Signal((data_width + 4, True))
            a3 = Signal((data_width + 4, True))
            self.comb += [
                a1.eq((x1 - xm1) >> 1),
                a2.eq((2*xm1 - 5*x0 + 4*x1 - x2) >> 1),
                a3.eq((-xm1 + 3*x0 - 3*x1 + x2) >> 1),
            ]
            # Horner: y = a0 + mu*(a1 + mu*(a2 + mu*a3)).
            y2 = Signal((data_width + 6, True))
            y1 = Signal((data_width + 6, True))
            self.comb += [
                y2.eq(a2 + ((mu*a3) >> frac_bits)),
                y1.eq(a1 + ((mu*y2) >> frac_bits)),
            ]
            y0, _ = scaled(a0*(1 << frac_bits) + mu*y1, frac_bits, data_width)
            self.sync += If(adv, getattr(self.source, field).eq(y0))

        valid = Signal()
        self.sync += If(adv, valid.eq(self.sink.valid))
        self.comb += self.source.valid.eq(valid)

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._mu = CSRStorage(self.frac_bits, name="mu", description="Fractional delay (Q.frac).")
        self.comb += self.mu.eq(self._mu.storage)
