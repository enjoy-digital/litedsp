#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import real_layout

# Goertzel -----------------------------------------------------------------------------------------

class LiteDSPGoertzel(LiteXModule):
    """Single-bin DFT (tone detector) via a 2nd-order resonator — one multiplier.

    For bin ``k`` of an ``N``-point window, runs ``s = x + (coeff*s1 - s2)`` with
    ``coeff = 2*cos(2*pi*k/N)``; after ``N`` samples emits the bin power
    ``s1**2 + s2**2 - coeff*s1*s2`` on ``source`` and restarts. Cheap DTMF / pilot detection.
    """
    def __init__(self, N, k, data_width=16, coeff_frac=14, with_csr=True):
        assert N >= 4                                     # Power pipeline spans 2 cycles.
        self.N = N
        self.k = k
        coeff = int(round(2*math.cos(2*math.pi*k/N)*(1 << coeff_frac)))  # 2*cos scaled by 2**coeff_frac.
        SW    = data_width + coeff_frac + 4                              # State width (growth margin).
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint([("data", 2*SW)])

        # # #

        # Resonator.
        # ----------
        s1, s2 = Signal((SW, True)), Signal((SW, True))  # State: s[n-1] / s[n-2].
        count  = Signal(max=N)                           # Position within the N-sample window.
        s      = Signal((SW, True))                      # s[n] (combinational).
        self.comb += [
            self.sink.ready.eq(1),  # Always accepts (no backpressure needed).
            s.eq(self.sink.data + ((coeff*s1) >> coeff_frac) - s2),
        ]

        # Power Pipeline.
        # ---------------
        # Power from the final states (new s1 = s, new s2 = s1), computed over a 2-stage
        # registered pipeline after the window boundary — done combinationally it chained three
        # multiplies onto the resonator and was the block's critical path. Bit-identical result,
        # emitted two cycles after the last window sample.
        f1, f2 = Signal((SW, True)), Signal((SW, True))  # Final states latched at window end.
        p1     = Signal((2*SW + 1, True))                # f1**2 + f2**2.
        p2     = Signal((2*SW + 1, True))                # coeff*f1*f2 (still scaled by coeff_frac).
        phase  = Signal(2)                               # Power pipeline stage (0: idle).
        self.sync += [
            If(self.source.valid & self.source.ready, self.source.valid.eq(0)),  # Held until consumed.
            If(self.sink.valid,
                s1.eq(s), s2.eq(s1),
                If(count == (N - 1),
                    count.eq(0), s1.eq(0), s2.eq(0),  # Restart the resonator for the next window.
                    f1.eq(s), f2.eq(s1),              # Latch final states (new s1/s2) for the power pipe.
                    phase.eq(1),
                ).Else(
                    count.eq(count + 1),
                )
            ),
            If(phase == 1,
                p1.eq(f1*f1 + f2*f2),
                p2.eq(coeff*((f1*f2) >> coeff_frac)),
                phase.eq(2),
            ).Elif(phase == 2,
                self.source.data.eq(p1 - (p2 >> coeff_frac)),
                self.source.valid.eq(1),
                phase.eq(0),
            ),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[CSRField("bin", size=16, description="Goertzel bin k.")])
        self.comb += self._config.fields.bin.eq(self.k)
