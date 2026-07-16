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
class LiteDSPFarrowInterpolator(LiteXModule):
    """Cubic (Catmull-Rom) Farrow fractional-delay interpolator with runtime ``mu``.

    Interpolates between samples at fractional position ``mu`` (Q.``frac_bits``, 0..1) using a
    4-tap window via Horner evaluation. The Catmull-Rom coefficients are all multiples of 1/2,
    so no awkward divides are needed. One output per input (a fractional delay); pair with a
    phase accumulator for arbitrary-ratio resampling.
    """
    def __init__(self, data_width=16, frac_bits=15, with_csr=True):
        self.data_width = data_width
        self.frac_bits  = frac_bits
        self.latency    = 7                      # Coefficient, then multiply/add Horner registers.
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.mu     = Signal(frac_bits)          # Fractional position in [0, 1).

        # # #

        # Handshake.
        # ----------
        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]
        mu = Signal((frac_bits + 1, True))       # Zero-extended to signed for the DSP multiplies.
        self.comb += mu.eq(self.mu)

        # Keep each sample's runtime fraction aligned with its Horner intermediates. Splitting
        # multiply and add across separate registers removes the DSP-to-carry-chain critical
        # paths while retaining one-sample-per-clock throughput.
        mu_d1 = Signal.like(mu)
        mu_d2 = Signal.like(mu)
        mu_d3 = Signal.like(mu)
        mu_d4 = Signal.like(mu)
        mu_d5 = Signal.like(mu)
        self.sync += If(adv,
            mu_d1.eq(mu),
            mu_d2.eq(mu_d1),
            mu_d3.eq(mu_d2),
            mu_d4.eq(mu_d3),
            mu_d5.eq(mu_d4),
        )

        # Datapath.
        # ---------
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
            # Horner: y = a0 + mu*(a1 + mu*(a2 + mu*a3)). Each multiply and following
            # addition gets its own register; coefficient delays preserve sample alignment.
            mul3_w = frac_bits + data_width + 5
            mul2_w = frac_bits + data_width + 7
            mul1_w = frac_bits + data_width + 7
            mul3   = Signal((mul3_w, True))
            mul2   = Signal((mul2_w, True))
            mul1   = Signal((mul1_w, True))
            y2     = Signal((data_width + 6, True))
            y1     = Signal((data_width + 6, True))
            a3_d1  = Signal.like(a3)
            a2_d1  = Signal.like(a2)
            a2_d2  = Signal.like(a2)
            a1_d1  = Signal.like(a1)
            a1_d2  = Signal.like(a1)
            a1_d3  = Signal.like(a1)
            a1_d4  = Signal.like(a1)
            a0_d1  = Signal.like(a0)
            a0_d2  = Signal.like(a0)
            a0_d3  = Signal.like(a0)
            a0_d4  = Signal.like(a0)
            a0_d5  = Signal.like(a0)
            a0_d6  = Signal.like(a0)
            self.sync += If(adv,
                a3_d1.eq(a3), a2_d1.eq(a2),              # Stage 1: coefficients.
                a1_d1.eq(a1), a0_d1.eq(a0),
                mul3.eq(mu_d1*a3_d1),                    # Stage 2: inner multiply.
                a2_d2.eq(a2_d1), a1_d2.eq(a1_d1), a0_d2.eq(a0_d1),
                y2.eq(a2_d2 + (mul3 >> frac_bits)),      # Stage 3: inner add.
                a1_d3.eq(a1_d2), a0_d3.eq(a0_d2),
                mul2.eq(mu_d3*y2),                       # Stage 4: middle multiply.
                a1_d4.eq(a1_d3), a0_d4.eq(a0_d3),
                y1.eq(a1_d4 + (mul2 >> frac_bits)),      # Stage 5: middle add.
                a0_d5.eq(a0_d4),
                mul1.eq(mu_d5*y1),                       # Stage 6: outer multiply.
                a0_d6.eq(a0_d5),
                getattr(self.source, field).eq(          # Stage 7: outer add/scale.
                    scaled(a0_d6*(1 << frac_bits) + mul1, frac_bits, data_width)[0]),
            )

        # Valid Pipeline.
        # ---------------
        valid_pipe = Signal(self.latency)
        self.sync += If(adv, valid_pipe.eq(Cat(self.sink.valid, valid_pipe[:-1])))
        self.comb += self.source.valid.eq(valid_pipe[-1])

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._mu = CSRStorage(self.frac_bits, name="mu", description="Fractional delay (Q.frac).")
        self.comb += self.mu.eq(self._mu.storage)
