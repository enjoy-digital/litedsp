#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Alpha blending of two pixel streams (constant alpha or a mask stream)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, pixel_layout, pixel_fields

# Alpha Blend --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPAlphaBlend(LiteXModule):
    """``y = rounded(a * A + (256 - a) * B, 8)`` per channel over two lock-stepped pixel streams.

    ``sink_a`` and ``sink_b`` (and the mono ``sink_alpha`` with ``with_alpha_sink``, its full
    scale mapping to 256) are joined; the framing comes from ``sink_a``. ``alpha`` is a 9-bit
    runtime value (256 = 1.0) when no alpha stream is used. Latency 1.
    """
    def __init__(self, data_width=8, n_channels=3, alpha=128, with_alpha_sink=False, with_csr=True):
        check(0 <= alpha <= 256, "expected 0 <= alpha <= 256")
        self.data_width = data_width
        self.n_channels = n_channels
        self.with_alpha_sink = with_alpha_sink
        self.latency    = 1
        self.sink_a = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.sink_b = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.alpha  = Signal(9, reset=alpha)
        sinks = [self.sink_a, self.sink_b]
        if with_alpha_sink:
            self.sink_alpha = stream.Endpoint(pixel_layout(data_width, 1))
            sinks.append(self.sink_alpha)

        # # #

        DW = data_width
        fields = pixel_fields(n_channels)
        adv = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        all_valid = Signal()
        self.comb += all_valid.eq(reduce_and([s.valid for s in sinks]))
        for k, s in enumerate(sinks):                                   # Ready from the other sinks only.
            others = [o.valid for j, o in enumerate(sinks) if j != k]
            self.comb += s.ready.eq(adv & reduce_and(others))
        a = Signal(9)
        if with_alpha_sink:
            full = (1 << DW) - 1
            self.comb += a.eq(Mux(self.sink_alpha.data == full, 256, self.sink_alpha.data[DW - 8:] if DW >= 8 else (self.sink_alpha.data << (8 - DW))))
        else:
            self.comb += a.eq(self.alpha)
        ia = Signal(9)
        self.comb += ia.eq(256 - a)
        for f in fields:
            p = Signal(DW + 10)
            self.comb += p.eq(self.sink_a.__getattr__(f)*a + self.sink_b.__getattr__(f)*ia)
            self.sync += If(adv, getattr(self.source, f).eq((p + 128) >> 8))
        self.sync += If(adv,
            self.source.valid.eq(all_valid),
            self.source.first.eq(self.sink_a.first), self.source.eol.eq(self.sink_a.eol), self.source.last.eq(self.sink_a.last),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._alpha = CSRStorage(9, reset=self.alpha.reset.value, name="alpha", description="Blend factor (256 = 1.0, unused with an alpha stream).")
        self.comb += self.alpha.eq(self._alpha.storage)

def reduce_and(terms):
    out = 1
    for t in terms:
        out = out & t
    return out
