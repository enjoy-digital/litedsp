#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Portable CIC (Cascaded-Integrator-Comb) decimator and interpolator.

Hogenauer CIC: N integrator stages, an R rate change, and N comb stages (differential delay
M). Integrators and combs use full-width **wrap-around** two's-complement arithmetic — the
intentional Hogenauer property whereby integrator overflow is cancelled by the combs as long
as the registers are wide enough (``data_width + ceil(N*log2(R*M))``). The output is rescaled
(round + saturate) by the CIC processing gain. R, N, M are build-time constants for exact
gain normalization. These replace the Xilinx CIC IP from the tetra design.
"""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled

# Helpers ------------------------------------------------------------------------------------------

def _growth_bits(R, N, M):
    return int(math.ceil(N*math.log2(R*M)))

# CIC Decimator ------------------------------------------------------------------------------------

@ResetInserter()
class CICDecimator(LiteXModule):
    """CIC decimator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N``, rescaled to width."""
    def __init__(self, data_width=16, R=8, N=3, M=1, with_csr=True):
        assert R >= 2 and N >= 1 and M >= 1
        growth = _growth_bits(R, N, M)
        W       = data_width + growth
        self.data_width = data_width
        self.R, self.N, self.M = R, N, M
        self.growth  = growth
        self.latency = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        adv    = Signal()
        is_out = Signal()
        xfer   = Signal()
        decim  = Signal(max=R)
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            is_out.eq(decim == (R - 1)),
            self.sink.ready.eq(Mux(is_out, adv, 1)),  # Drop freely; stall only on output beats.
            xfer.eq(self.sink.valid & self.sink.ready),
        ]
        self.sync += If(xfer, If(is_out, decim.eq(0)).Else(decim.eq(decim + 1)))

        for field in ["i", "q"]:
            x = getattr(self.sink, field)

            # Integrators (combinational cascade, registered, wrap-around).
            integ = [Signal((W, True)) for _ in range(N)]
            nxt   = []
            prev  = x
            for k in range(N):
                nk = Signal((W, True))
                self.comb += nk.eq(integ[k] + prev)
                nxt.append(nk)
                prev = nk
            self.sync += If(xfer, *[integ[k].eq(nxt[k]) for k in range(N)])

            # Comb stages at the decimated rate (M-deep differential delay).
            combq = [[Signal((W, True)) for _ in range(M)] for _ in range(N)]
            c     = nxt[N - 1]
            ins   = []
            for k in range(N):
                d = Signal((W, True))
                self.comb += d.eq(c - combq[k][M - 1])
                ins.append(c)
                c = d
            self.sync += If(xfer & is_out, *[
                combq[k][0].eq(ins[k]) for k in range(N)
            ], *[
                combq[k][m].eq(combq[k][m - 1]) for k in range(N) for m in range(1, M)
            ])

            out, _ = scaled(c, growth, data_width)
            self.sync += [
                If(xfer & is_out,
                    getattr(self.source, field).eq(out),
                ),
            ]

        self.sync += [
            If(xfer & is_out, self.source.valid.eq(1)).Elif(adv, self.source.valid.eq(0)),
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("rate",   size=16, description="Decimation factor R."),
            CSRField("stages", size=8,  description="CIC stages N."),
        ])
        self.comb += [self._config.fields.rate.eq(self.R), self._config.fields.stages.eq(self.N)]

# CIC Interpolator ---------------------------------------------------------------------------------

@ResetInserter()
class CICInterpolator(LiteXModule):
    """CIC interpolator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N / R``, rescaled."""
    def __init__(self, data_width=16, R=8, N=3, M=1, with_csr=True):
        assert R >= 2 and N >= 1 and M >= 1
        growth = int(math.ceil(N*math.log2(R*M) - math.log2(R)))
        W       = data_width + _growth_bits(R, N, M)
        self.data_width = data_width
        self.R, self.N, self.M = R, N, M
        self.growth  = growth
        self.latency = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        adv   = Signal()
        first = Signal()        # Start of an output group (consume one input).
        phase = Signal(max=R)
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            first.eq(phase == 0),
            self.sink.ready.eq(first & adv),
        ]
        take = Signal()         # Consuming a new input sample this beat.
        self.comb += take.eq(first & self.sink.valid & adv)
        emit = Signal()         # Producing an output sample this beat.
        self.comb += emit.eq(adv & (~first | self.sink.valid))
        self.sync += If(emit,
            If(phase == (R - 1), phase.eq(0)).Else(phase.eq(phase + 1)),
        )

        for field in ["i", "q"]:
            x = getattr(self.sink, field)

            # Comb stages at the input rate (run once per input sample).
            combq = [[Signal((W, True)) for _ in range(M)] for _ in range(N)]
            c     = Signal((W, True))
            self.comb += c.eq(x)
            ins   = []
            cval  = c
            for k in range(N):
                d = Signal((W, True))
                self.comb += d.eq(cval - combq[k][M - 1])
                ins.append(cval)
                cval = d
            self.sync += If(take, *[
                combq[k][0].eq(ins[k]) for k in range(N)
            ], *[
                combq[k][m].eq(combq[k][m - 1]) for k in range(N) for m in range(1, M)
            ])

            # Rate expand (zero-stuff) + integrators at the output rate.
            integ = [Signal((W, True)) for _ in range(N)]
            stuff = Signal((W, True))
            self.comb += stuff.eq(Mux(take, cval, 0))   # Comb output on group start, else zero.
            nxt   = []
            prev  = stuff
            for k in range(N):
                nk = Signal((W, True))
                self.comb += nk.eq(integ[k] + prev)
                nxt.append(nk)
                prev = nk
            self.sync += If(emit, *[integ[k].eq(nxt[k]) for k in range(N)])

            out, _ = scaled(nxt[N - 1], growth, data_width)
            self.sync += If(emit, getattr(self.source, field).eq(out))

        self.sync += If(emit, self.source.valid.eq(1)).Elif(adv, self.source.valid.eq(0))

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("rate",   size=16, description="Interpolation factor R."),
            CSRField("stages", size=8,  description="CIC stages N."),
        ])
        self.comb += [self._config.fields.rate.eq(self.R), self._config.fields.stages.eq(self.N)]
