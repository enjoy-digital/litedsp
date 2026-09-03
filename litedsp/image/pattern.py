#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Test pattern source: constant, ramps, colour bars, checkerboard, counter and a Bayer mosaic."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, pixel_layout, pixel_fields

PATTERN_CONST, PATTERN_RAMP, PATTERN_BARS, PATTERN_CHECKER, PATTERN_COUNTER, PATTERN_BAYER = range(6)
PATTERNS = ("const", "ramp", "bars", "checker", "counter", "bayer")
# LiteX colour-bar order: white, yellow, cyan, green, magenta, red, blue, black (r, g, b on/off).
BARS = [(1, 1, 1), (1, 1, 0), (0, 1, 1), (0, 1, 0), (1, 0, 1), (1, 0, 0), (0, 0, 1), (0, 0, 0)]

# Pixel Pattern ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPixelPattern(LiteXModule):
    """Framed raster test-pattern source (``pixel_layout``), geometry from CSRs.

    Runtime ``mode``: ``const`` (``const_r/g/b``), ``ramp`` (``r = x``, ``g = y``, ``b = x + y``
    modulo the code range; mono: ``x``), ``bars`` (eight LiteX-order colour bars, the last bar
    absorbs the remainder of ``width``), ``checker`` (8 x 8 full-scale checks), ``counter``
    (the pixel index within the frame on every channel) and ``bayer`` (the colour bars sampled
    on an RGGB mosaic, one channel). ``enable`` streams frames back to back, ``trigger`` sends
    one frame; ``width`` / ``height`` are runtime (reset to the build values). Status: ``busy``
    and the frame count. Source-only, one pixel per cycle.
    """
    def __init__(self, data_width=8, n_channels=3, width=640, height=480, mode="bars", coord_bits=12,
        with_csr=True):
        check(mode in PATTERNS, f"expected mode in {PATTERNS}")
        check(8 <= width < 2**coord_bits and 1 <= height < 2**coord_bits, "expected 8 <= width, 1 <= height < 2**coord_bits")
        self.data_width = data_width
        self.n_channels = n_channels
        self.coord_bits = coord_bits
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.mode    = Signal(3, reset=PATTERNS.index(mode))
        self.width   = Signal(coord_bits, reset=width)
        self.height  = Signal(coord_bits, reset=height)
        self.const   = [Signal(data_width, reset=(1 << data_width) - 1, name=f"const{k}") for k in range(3)]
        self.enable  = Signal()
        self.trigger = Signal()
        self.busy    = Signal()
        self.frames  = Signal(32)

        # # #

        DW = data_width
        full = (1 << DW) - 1
        adv  = Signal()
        x, y = Signal(coord_bits), Signal(coord_bits)
        bar, px = Signal(3), Signal(coord_bits)                         # Bar index, pixel in bar.
        bar_w = Signal(coord_bits)
        count = Signal(DW)
        eol, last = Signal(), Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            bar_w.eq(self.width >> 3),
            eol.eq(x == self.width - 1),
            last.eq(eol & (y == self.height - 1)),
        ]
        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            If(self.enable | self.trigger,
                NextValue(x, 0), NextValue(y, 0), NextValue(bar, 0), NextValue(px, 0), NextValue(count, 0),
                NextState("RUN"),
            ),
        )
        fsm.act("RUN",
            self.busy.eq(1),
            If(adv,
                NextValue(count, count + 1),
                If(eol,
                    NextValue(x, 0), NextValue(bar, 0), NextValue(px, 0),
                    If(last,
                        NextValue(y, 0), NextValue(count, 0),
                        NextValue(self.frames, self.frames + 1),
                        If(~self.enable, NextState("IDLE")),
                    ).Else(
                        NextValue(y, y + 1),
                    ),
                ).Else(
                    NextValue(x, x + 1),
                    If((px == bar_w - 1) & (bar != 7),
                        NextValue(px, 0), NextValue(bar, bar + 1),
                    ).Else(
                        NextValue(px, px + 1),
                    ),
                ),
            ),
        )
        # Pixel values per mode.
        bar_rgb = [Signal(DW, name=f"bar_{c}") for c in range(3)]
        for c in range(3):
            self.comb += bar_rgb[c].eq(Array([full if on[c] else 0 for on in BARS])[bar])
        checker = Signal(DW)
        self.comb += checker.eq(Mux(x[3] ^ y[3], full, 0))
        ramp = [Signal(DW, name=f"ramp{c}") for c in range(3)]
        self.comb += [ramp[0].eq(x), ramp[1].eq(y), ramp[2].eq(x + y)]
        bayer = Signal(DW)
        self.comb += bayer.eq(Mux(y[0], Mux(x[0], bar_rgb[2], bar_rgb[1]), Mux(x[0], bar_rgb[1], bar_rgb[0])))
        def value(c):
            return Mux(self.mode == PATTERN_CONST, self.const[c],
                   Mux(self.mode == PATTERN_RAMP, ramp[c],
                   Mux(self.mode == PATTERN_BARS, bar_rgb[c],
                   Mux(self.mode == PATTERN_CHECKER, checker,
                   Mux(self.mode == PATTERN_COUNTER, count, bayer)))))
        self.sync += If(adv,
            self.source.valid.eq(fsm.ongoing("RUN")),
            self.source.eol.eq(eol), self.source.first.eq((x == 0) & (y == 0)), self.source.last.eq(last),
            *[getattr(self.source, f).eq(value(c if n_channels == 3 else 0)) for c, f in enumerate(pixel_fields(n_channels))],
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        CB, DW = self.coord_bits, self.data_width
        self._control = CSRStorage(fields=[
            CSRField("enable",  size=1, offset=0, description="Stream frames continuously."),
            CSRField("trigger", size=1, offset=1, pulse=True, description="Send one frame."),
            CSRField("mode",    size=3, offset=4, reset=self.mode.reset.value, description="0 const, 1 ramp, 2 bars, 3 checker, 4 counter, 5 bayer."),
        ])
        self._geometry = CSRStorage(fields=[
            CSRField("width",  size=CB, offset=0,  reset=self.width.reset.value,  description="Pixels per line."),
            CSRField("height", size=CB, offset=16, reset=self.height.reset.value, description="Lines per frame."),
        ])
        self._const = CSRStorage(fields=[
            CSRField("r", size=DW, offset=0,  reset=(1 << DW) - 1, description="Constant red / mono value."),
            CSRField("g", size=DW, offset=8 if DW <= 8 else 16, reset=(1 << DW) - 1, description="Constant green."),
            CSRField("b", size=DW, offset=16 if DW <= 8 else 32, reset=(1 << DW) - 1, description="Constant blue."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("busy", size=1, offset=0, description="A frame is being sent."),
        ])
        self._frames = CSRStatus(32, name="frames", description="Frames sent since reset.")
        self.comb += [
            self.enable.eq(self._control.fields.enable), self.trigger.eq(self._control.fields.trigger),
            self.mode.eq(self._control.fields.mode),
            self.width.eq(self._geometry.fields.width), self.height.eq(self._geometry.fields.height),
            self.const[0].eq(self._const.fields.r), self.const[1].eq(self._const.fields.g), self.const[2].eq(self._const.fields.b),
            self._status.fields.busy.eq(self.busy), self._frames.status.eq(self.frames),
        ]
