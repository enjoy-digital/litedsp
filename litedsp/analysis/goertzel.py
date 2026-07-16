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

from litedsp.common import check, real_layout

# Goertzel -----------------------------------------------------------------------------------------

class LiteDSPGoertzel(LiteXModule):
    """Single-bin DFT (tone detector) via a 2nd-order resonator — one multiplier.

    For bin ``k`` of an ``N``-point window, runs ``s = x + (coeff*s1 - s2)`` with
    ``coeff = 2*cos(2*pi*k/N)``; after ``N`` samples emits the bin power
    ``s1**2 + s2**2 - coeff*s1*s2`` on ``source`` and restarts. Cheap DTMF / pilot detection.

    Parameters
    ----------
    k : int
        Target DFT bin index (0..N-1); the detected tone frequency is ``k*f_sample/N``.
    coeff_frac : int
        Fractional bits of the fixed-point resonator coefficient ``2*cos(2*pi*k/N)``; more bits
        sharpen the bin frequency but widen the state registers (data_width + coeff_frac + 4).
    """
    def __init__(self, N, k, data_width=16, coeff_frac=14, architecture="classic",
        with_csr=True):
        check(N >= 4, "expected N >= 4")  # Power pipeline spans 2 cycles.
        check(architecture in ("classic", "folded"),
            "architecture must be 'classic' or 'folded'.")
        self.N = N
        self.k = k
        self.architecture    = architecture
        self.sample_interval = 1 if architecture == "classic" else 2
        coeff = int(round(2*math.cos(2*math.pi*k/N)*(1 << coeff_frac)))  # 2*cos scaled by 2**coeff_frac.
        SW    = data_width + coeff_frac + 4                              # State width (growth margin).
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint([("data", 2*SW)])
        self.latency = None  # Variable (one result per N-sample window).

        # # #

        # Resonator.
        # ----------
        s1, s2 = Signal((SW, True)), Signal((SW, True))  # State: s[n-1] / s[n-2].
        count  = Signal(max=N)                           # Position within the N-sample window.
        s      = Signal((SW, True))                      # s[n] (combinational).
        f1, f2 = Signal((SW, True)), Signal((SW, True))  # Final states latched at window end.
        phase  = Signal(2)                               # Power pipeline stage (0: idle).
        if architecture == "classic":
            self.comb += [
                self.sink.ready.eq(1),  # Always accepts (no backpressure needed).
                s.eq(self.sink.data + ((coeff*s1) >> coeff_frac) - s2),
            ]
        else:
            # The recurrence is feedback-bound.  Fold it over two clocks: capture x, old
            # states and the coefficient product, then add/subtract and update the states.
            pending = Signal()
            x_r     = Signal((data_width, True))
            s1_r    = Signal((SW, True))
            s2_r    = Signal((SW, True))
            mul_r   = Signal((SW + coeff_frac + 2, True))
            accept  = Signal()
            self.comb += [
                self.sink.ready.eq(~pending),
                accept.eq(self.sink.valid & self.sink.ready),
                s.eq(x_r + (mul_r >> coeff_frac) - s2_r),
            ]
            self.sync += [
                If(accept,
                    x_r.eq(self.sink.data), s1_r.eq(s1), s2_r.eq(s2),
                    mul_r.eq(coeff*s1), pending.eq(1),
                ),
                If(pending,
                    s1.eq(s), s2.eq(s1_r), pending.eq(0),
                    If(count == (N - 1),
                        count.eq(0), s1.eq(0), s2.eq(0),
                        f1.eq(s), f2.eq(s1_r), phase.eq(1),
                    ).Else(
                        count.eq(count + 1),
                    ),
                ),
            ]

        # Power Pipeline.
        # ---------------
        # Power from the final states (new s1 = s, new s2 = s1), computed over a 3-stage
        # registered pipeline after the window boundary. The cross-product and its coefficient
        # multiply are separate timing cones. Arithmetic remains bit-identical.
        p1     = Signal((2*SW + 1, True))                # f1**2 + f2**2.
        cross  = Signal((2*SW, True))                    # f1*f2, registered before coeff multiply.
        p2     = Signal((2*SW + 1, True))                # coeff*f1*f2 (still scaled by coeff_frac).
        self.sync += If(self.source.valid & self.source.ready, self.source.valid.eq(0))
        if architecture == "classic":
            self.sync += If(self.sink.valid,
                s1.eq(s), s2.eq(s1),
                If(count == (N - 1),
                    count.eq(0), s1.eq(0), s2.eq(0),  # Restart the resonator for the next window.
                    f1.eq(s), f2.eq(s1),              # Latch final states (new s1/s2) for the power pipe.
                    phase.eq(1),
                ).Else(
                    count.eq(count + 1),
                )
            )
        self.sync += [
            If(phase == 1,
                p1.eq(f1*f1 + f2*f2),
                cross.eq(f1*f2),
                phase.eq(2),
            ).Elif(phase == 2,
                p2.eq(coeff*(cross >> coeff_frac)),
                phase.eq(3),
            ).Elif(phase == 3,
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
