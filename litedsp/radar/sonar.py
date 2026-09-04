#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Sonar-specific blocks: time-varying gain."""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common       import check, iq_layout, scaled, bits_for
from litedsp.level.logdb  import LiteDSPExp2
from litedsp.stream.split import LiteDSPSplit
from litedsp.stream.delay import LiteDSPDelay

# Time-Varying Gain --------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPTVG(LiteXModule):
    """Time-varying gain: a log-domain gain ramp along the range bins of each frame.

    The gain in log2 units (Q.gain_frac) is ``g(r) = g0 + k_log * log2(r) + k_lin * r`` for
    range bin ``r`` (a counter restarted by ``first``; ``log2(r)`` from a ROM), clamped to
    ``[-2**max_gain_log2, 2**max_gain_log2)``, turned into a linear gain by
    :class:`LiteDSPExp2` (Q.14) and applied as ``y = scaled(x * gain, 14, data_width)`` with the
    sticky ``saturated`` flag. The sample rides a matching-latency
    :class:`LiteDSPDelay` branch behind a :class:`LiteDSPSplit`, so ``bypass`` is an exact
    same-latency passthrough. ``litedsp.radar.design.tvg_coefficients`` gives the words for a
    ``db_per_decade * log10(r) + alpha * r + g0`` law (40 dB/decade = two-way spherical
    spreading). Latency 6.
    """
    def __init__(self, n_range_bins=1024, data_width=16, gain_frac=8, max_gain_log2=8,
                 with_csr=True):
        check(n_range_bins >= 2, "expected n_range_bins >= 2")
        check(1 <= gain_frac <= 12 and 1 <= max_gain_log2 <= 12,
              "expected 1 <= gain_frac, max_gain_log2 <= 12")
        self.n_range_bins  = n_range_bins
        self.data_width    = data_width
        self.gain_frac     = gain_frac
        self.max_gain_log2 = max_gain_log2
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        GF, GW = gain_frac, gain_frac + max_gain_log2 + 1                # Log2 gain: signed Q.GF.
        self.g0     = Signal((GW, True))                                # Log2 gain at bin 0.
        self.k_log  = Signal((GW, True))                                # Per log2(r), Q.GF.
        self.k_lin  = Signal((GW, True))                                # Per bin, Q.GF.
        self.bypass = Signal()
        self.saturated = Signal()
        self.clear     = Signal()

        # # #

        N  = n_range_bins
        RW = bits_for(N - 1)
        OF = 14                                                         # Linear gain fraction bits.
        self.split = LiteDSPSplit(2, layout=iq_layout(data_width))
        self.exp2  = LiteDSPExp2(in_width=GW, frac_bits=GF, out_frac=OF,
                                 out_width=OF + max_gain_log2 + 1, with_csr=False)
        gain_latency = 3 + self.exp2.latency                   # Counter/ROM, products, sum -> exp2.
        self.delay = LiteDSPDelay(gain_latency, layout=iq_layout(data_width))
        self.latency = gain_latency + 1
        self.tags = stream.SyncFIFO([("pad", 1)], self.latency + 4)    # first / last alongside.
        self.comb += [
            self.sink.connect(self.split.sink),
            self.split.sources[1].connect(self.delay.sink),
            self.tags.sink.valid.eq(self.sink.valid & self.sink.ready),
            self.tags.sink.first.eq(self.sink.first), self.tags.sink.last.eq(self.sink.last),
            self.tags.source.ready.eq(self.source.valid & self.source.ready),
        ]

        # Gain branch: range counter + log2 ROM (S1), products (S2), clamped sum (S3) -> Exp2.
        # -------------------------------------------------------------------------------------
        LW = RW + GF
        rom = Memory(LW, N, init=[0] + [int(round(math.log2(r)*(1 << GF))) for r in range(1, N)])
        self.specials += rom
        rp = rom.get_port(has_re=True)
        self.specials += rp
        gs   = self.split.sources[0]
        adv  = Signal()
        xfer = Signal()
        r    = Signal(max=N)
        self.comb += [
            adv.eq(self.exp2.sink.ready | ~self.exp2.sink.valid),       # Feeding an elastic sink.
            gs.ready.eq(adv),
            xfer.eq(gs.valid & gs.ready),
            rp.adr.eq(Mux(gs.first, 0, r)), rp.re.eq(adv),
        ]
        self.sync += If(xfer,
            # Holds at N-1.
            If(gs.first, r.eq(1 % N)).Elif(r == N - 1, r.eq(N - 1)).Else(r.eq(r + 1)),
        )
        v1, v2, v3 = Signal(), Signal(), Signal()
        r1  = Signal(max=N)
        rs1 = Signal((RW + 1, True))
        log1 = Signal((LW + 1, True))
        pl, pr = Signal((LW + 1 + GW, True)), Signal((RW + 1 + GW, True))
        g2  = Signal((LW + 2 + GW + 1, True))
        g3  = Signal((GW, True))
        lim_hi, lim_lo = (1 << (GW - 1)) - 1, -(1 << (GW - 1))
        self.comb += [rs1.eq(r1), log1.eq(rp.dat_r)]
        self.sync += If(adv,
            v1.eq(xfer), r1.eq(rp.adr),
            v2.eq(v1), pl.eq(log1*self.k_log), pr.eq(rs1*self.k_lin),
            v3.eq(v2), g2.eq(self.g0 + ((pl + (1 << (GF - 1))) >> GF) + pr),
        )
        self.comb += [
            g3.eq(Mux(g2 > lim_hi, lim_hi, Mux(g2 < lim_lo, lim_lo, g2))),
            self.exp2.sink.valid.eq(v3), self.exp2.sink.data.eq(g3),
        ]

        # Join: sample x gain, scaled; bypass passes the delayed sample.
        # ---------------------------------------------------------------
        oadv = Signal()
        both = Signal()
        gain = self.exp2.source.data
        GLW  = len(gain)
        pi, pq = Signal((data_width + GLW + 1, True)), Signal((data_width + GLW + 1, True))
        gsig = Signal((GLW + 1, True))
        self.comb += [
            oadv.eq(self.source.ready | ~self.source.valid),
            both.eq(self.exp2.source.valid & self.delay.source.valid),
            self.exp2.source.ready.eq(oadv & self.delay.source.valid),
            self.delay.source.ready.eq(oadv & self.exp2.source.valid),
            gsig.eq(gain),
            pi.eq(self.delay.source.i*gsig), pq.eq(self.delay.source.q*gsig),
        ]
        yi, ovi = scaled(pi, OF, data_width)
        yq, ovq = scaled(pq, OF, data_width)
        self.comb += [self.source.first.eq(self.tags.source.first),
                      self.source.last.eq(self.tags.source.last)]
        self.sync += [
            If(oadv,
                self.source.valid.eq(both),
                If(self.bypass,
                    self.source.i.eq(self.delay.source.i), self.source.q.eq(self.delay.source.q),
                ).Else(
                    self.source.i.eq(yi), self.source.q.eq(yq),
                ),
            ),
            If(self.clear, self.saturated.eq(0)).Elif(
                oadv & both & ~self.bypass & (ovi | ovq), self.saturated.eq(1)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        GW = len(self.g0)
        self._g0    = CSRStorage(GW, name="g0",
                                 description=f"Log2 gain at bin 0 (signed Q.{self.gain_frac}).")
        self._k_log = CSRStorage(GW, name="k_log", description="Log2 gain per log2(range bin).")
        self._k_lin = CSRStorage(GW, name="k_lin", description="Log2 gain per range bin.")
        self._control = CSRStorage(fields=[
            CSRField("bypass", size=1, offset=0, description="Pass the samples unchanged (same latency)."),
            CSRField("clear",  size=1, offset=1, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturated", size=1, offset=0, description="Sticky: an output saturated."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("gain_frac",     size=4,  offset=0,  description="Log2 gain fractional bits."),
            CSRField("max_gain_log2", size=4,  offset=4,  description="Gain clamp (2^max_gain_log2)."),
            CSRField("n_range_bins",  size=16, offset=8,  description="Range bins per frame."),
        ])
        self.comb += [
            self.g0.eq(self._g0.storage), self.k_log.eq(self._k_log.storage),
            self.k_lin.eq(self._k_lin.storage),
            self.bypass.eq(self._control.fields.bypass), self.clear.eq(self._control.fields.clear),
            self._status.fields.saturated.eq(self.saturated),
            self._config.fields.gain_frac.eq(self.gain_frac),
            self._config.fields.max_gain_log2.eq(self.max_gain_log2),
            self._config.fields.n_range_bins.eq(self.n_range_bins),
        ]
