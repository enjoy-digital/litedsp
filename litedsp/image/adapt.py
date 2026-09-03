#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Pixel word packing for framebuffers / DMA and its inverse."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, pixel_layout

FORMATS = ("rgb888", "xrgb8888", "rgb565", "mono")

def _word_width(fmt, data_width):
    return {"rgb888": 3*data_width, "xrgb8888": 32, "rgb565": 16, "mono": data_width}[fmt]

# Pixel Pack ---------------------------------------------------------------------------------------

class LiteDSPPixelPack(LiteXModule):
    """Pack pixels into memory words: ``rgb888`` (``r`` in the low byte, then ``g``, ``b``),
    ``xrgb8888`` (little-endian XRGB: ``b`` low byte, ``g``, ``r``, zero), ``rgb565`` and
    ``mono``. Combinational (latency 0); ``eol`` is dropped, ``first`` / ``last`` kept."""
    def __init__(self, data_width=8, format="rgb888"):
        check(format in FORMATS, f"expected format in {FORMATS}")
        check(data_width == 8 or format in ("rgb888", "mono"), "expected data_width 8 for xrgb8888 / rgb565")
        self.data_width = data_width
        self.format     = format
        self.latency    = 0
        nc = 1 if format == "mono" else 3
        self.sink   = stream.Endpoint(pixel_layout(data_width, nc))
        self.source = stream.Endpoint([("data", _word_width(format, data_width))])

        # # #

        s = self.sink
        word = {
            "rgb888":   lambda: Cat(s.r, s.g, s.b),
            "xrgb8888": lambda: Cat(s.b, s.g, s.r, C(0, 8)),
            "rgb565":   lambda: Cat(s.b[3:], s.g[2:], s.r[3:]),
            "mono":     lambda: s.data,
        }[format]()
        self.comb += [
            self.sink.connect(self.source, omit={"data", "r", "g", "b", "eol"}),
            self.source.data.eq(word),
        ]

# Pixel Unpack -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPixelUnpack(LiteXModule):
    """Unpack memory words back into pixels (inverse of :class:`LiteDSPPixelPack`; ``rgb565``
    zero-fills the low bits) and regenerate ``eol`` from a column counter against the runtime
    ``width`` (``first`` restarts it). Latency 1."""
    def __init__(self, data_width=8, format="rgb888", width=640, coord_bits=12, with_csr=True):
        check(format in FORMATS, f"expected format in {FORMATS}")
        check(data_width == 8 or format in ("rgb888", "mono"), "expected data_width 8 for xrgb8888 / rgb565")
        check(2 <= width < 2**coord_bits, "expected 2 <= width < 2**coord_bits")
        self.data_width = data_width
        self.format     = format
        self.coord_bits = coord_bits
        self.latency    = 1
        nc = 1 if format == "mono" else 3
        self.sink   = stream.Endpoint([("data", _word_width(format, data_width))])
        self.source = stream.Endpoint(pixel_layout(data_width, nc))
        self.width  = Signal(coord_bits, reset=width)

        # # #

        adv, xfer = Signal(), Signal()
        col = Signal(coord_bits)
        c   = Signal(coord_bits)
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
            c.eq(Mux(self.sink.first, 0, col)),
        ]
        self.sync += If(xfer, If((c == self.width - 1) | self.sink.last, col.eq(0)).Else(col.eq(c + 1)))
        d = self.sink.data
        if format == "rgb888":
            fields = [(self.source.r, d[0:data_width]), (self.source.g, d[data_width:2*data_width]), (self.source.b, d[2*data_width:3*data_width])]
        elif format == "xrgb8888":
            fields = [(self.source.b, d[0:8]), (self.source.g, d[8:16]), (self.source.r, d[16:24])]
        elif format == "rgb565":
            fields = [(self.source.b, Cat(C(0, 3), d[0:5])), (self.source.g, Cat(C(0, 2), d[5:11])), (self.source.r, Cat(C(0, 3), d[11:16]))]
        else:
            fields = [(self.source.data, d)]
        self.sync += If(adv,
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first), self.source.last.eq(self.sink.last),
            self.source.eol.eq((c == self.width - 1) | self.sink.last),
            *[dst.eq(src) for dst, src in fields],
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._width = CSRStorage(self.coord_bits, reset=self.width.reset.value, name="width", description="Pixels per line (eol regeneration).")
        self.comb += self.width.eq(self._width.storage)
