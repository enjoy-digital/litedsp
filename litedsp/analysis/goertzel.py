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

class Goertzel(LiteXModule):
    """Single-bin DFT (tone detector) via a 2nd-order resonator — one multiplier.

    For bin ``k`` of an ``N``-point window, runs ``s = x + (coeff*s1 - s2)`` with
    ``coeff = 2*cos(2*pi*k/N)``; after ``N`` samples emits the bin power
    ``s1**2 + s2**2 - coeff*s1*s2`` on ``source`` and restarts. Cheap DTMF / pilot detection.
    """
    def __init__(self, N, k, data_width=16, coeff_frac=14, with_csr=True):
        self.N = N
        self.k = k
        coeff = int(round(2*math.cos(2*math.pi*k/N)*(1 << coeff_frac)))
        SW    = data_width + coeff_frac + 4
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint([("data", 2*SW)])

        # # #

        s1, s2 = Signal((SW, True)), Signal((SW, True))
        count  = Signal(max=N)
        s      = Signal((SW, True))
        self.comb += [
            self.sink.ready.eq(1),
            s.eq(self.sink.data + ((coeff*s1) >> coeff_frac) - s2),
        ]
        # Power from the post-update states (new s1 = s, new s2 = s1).
        power = Signal((2*SW, True))
        self.comb += power.eq(s*s + s1*s1 - ((coeff*((s*s1) >> coeff_frac)) >> coeff_frac))
        self.sync += [
            If(self.source.valid & self.source.ready, self.source.valid.eq(0)),
            If(self.sink.valid,
                s1.eq(s), s2.eq(s1),
                If(count == (N - 1),
                    count.eq(0), s1.eq(0), s2.eq(0),
                    self.source.data.eq(power),
                    self.source.valid.eq(1),
                ).Else(
                    count.eq(count + 1),
                )
            )
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[CSRField("bin", size=16, description="Goertzel bin k.")])
        self.comb += self._config.fields.bin.eq(self.k)
