#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteX video interop: timed video streams (blanking, syncs) to and from framed pixel streams."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourcePulse
from litex.soc.interconnect                  import stream

from litedsp.common import check, pixel_layout, video_layout, video_timing_layout

# Pixel From Video ---------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPixelFromVideo(LiteXModule):
    """LiteX ``video_data_layout`` stream to a framed RGB pixel stream.

    Blanking beats (``de = 0``) are consumed unconditionally; active pixels are framed from the
    syncs: the column restarts on the rising edge of ``de``, the row on the rising edge of
    ``vsync``, ``first`` marks the first active pixel after a vsync, ``eol`` the pixel at
    ``width - 1`` and ``last`` the ``eol`` of row ``height - 1`` (runtime geometry CSRs). A line
    shorter or longer than ``width`` sets the sticky ``geometry_error``. Latency 1.
    """
    def __init__(self, data_width=8, width=640, height=480, coord_bits=12, with_csr=True):
        check(2 <= width < 2**coord_bits and 1 <= height < 2**coord_bits, "expected 2 <= width, 1 <= height < 2**coord_bits")
        self.data_width = data_width
        self.coord_bits = coord_bits
        self.latency    = 1
        self.sink   = stream.Endpoint(video_layout(data_width))
        self.source = stream.Endpoint(pixel_layout(data_width, 3))
        self.width  = Signal(coord_bits, reset=width)
        self.height = Signal(coord_bits, reset=height)
        self.clear  = Signal()
        self.geometry_error = Signal()
        self.frames = Signal(32)

        # # #

        adv  = Signal()
        xfer = Signal()
        de_d, vs_d = Signal(), Signal()                                  # Previous accepted beat.
        col, row = Signal(coord_bits), Signal(coord_bits)
        armed = Signal()                                                # A vsync has been seen.
        pending_first = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv | ~self.sink.de),                    # Blanking never waits.
            xfer.eq(self.sink.valid & self.sink.ready),
        ]
        active  = Signal()
        line_start = Signal()
        self.comb += [
            active.eq(xfer & self.sink.de),
            line_start.eq(active & ~de_d),
        ]
        c = Signal(coord_bits)
        self.comb += c.eq(Mux(line_start, 0, col))
        eol  = Signal()
        self.comb += eol.eq(active & (c == self.width - 1))
        self.sync += [
            If(xfer,
                de_d.eq(self.sink.de), vs_d.eq(self.sink.vsync),
                If(self.sink.vsync & ~vs_d,
                    row.eq(0), armed.eq(1), pending_first.eq(1),
                ),
                If(active,
                    col.eq(c + 1),
                ),
                # Line end: the falling edge of de closes the line; a short / long line is an error.
                If(~self.sink.de & de_d,
                    col.eq(0),
                    If(col != self.width, self.geometry_error.eq(1)),  # The row still advances.
                    If(row != self.height - 1, row.eq(row + 1)).Else(self.frames.eq(self.frames + 1)),
                ),
                If(active & (c >= self.width), self.geometry_error.eq(1)),
                If(active, pending_first.eq(0)),
            ),
            If(self.clear, self.geometry_error.eq(0)),
        ]
        self.sync += If(adv,
            self.source.valid.eq(active & armed),
            self.source.r.eq(self.sink.r), self.source.g.eq(self.sink.g), self.source.b.eq(self.sink.b),
            self.source.eol.eq(eol),
            self.source.first.eq(active & pending_first),
            self.source.last.eq(eol & (row == self.height - 1)),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        CB = self.coord_bits
        self._geometry = CSRStorage(fields=[
            CSRField("width",  size=CB, offset=0,  reset=self.width.reset.value,  description="Active pixels per line."),
            CSRField("height", size=CB, offset=16, reset=self.height.reset.value, description="Active lines per frame."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the geometry error."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("geometry_error", size=1, offset=0, description="Sticky: a line did not match the width."),
        ])
        self._frames = CSRStatus(32, name="frames", description="Frames received.")
        self.comb += [
            self.width.eq(self._geometry.fields.width), self.height.eq(self._geometry.fields.height),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.geometry_error.eq(self.geometry_error),
            self._frames.status.eq(self.frames),
        ]

# Pixel To Video -----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPixelToVideo(LiteXModule):
    """Framed RGB pixels onto a LiteX timing-generator stream (``video_timing_layout``) as a
    ``video_data_layout`` stream.

    ``vtg_sink`` paces the output: every timing beat produces one video beat (blanking beats
    carry black), each active (``de``) beat pulls one pixel from ``sink``. The FSM starts in SYNC
    (black output, stale pixels dropped and counted until the timing stream's frame start meets
    a ``first`` pixel) and runs from there; an active beat without a pixel outputs black, sets the
    sticky ``underflow`` and counts it (optional ``ev.underflow``); ``first`` arriving elsewhere
    than at a frame start re-synchronises. Latency 1 (timing beat to video beat); the pixel
    rate follows the timing (cosim excluded).
    """
    def __init__(self, data_width=8, coord_bits=12, with_csr=True, with_irq=False):
        self.data_width = data_width
        self.coord_bits = coord_bits
        self.latency    = 1
        self.sink     = stream.Endpoint(pixel_layout(data_width, 3))
        self.vtg_sink = stream.Endpoint(video_timing_layout(coord_bits))
        self.source   = stream.Endpoint(video_layout(data_width))
        self.underflow = Signal()                                       # Sticky.
        self.underflows = Signal(32)
        self.dropped    = Signal(32)
        self.clear      = Signal()
        self.synced     = Signal()

        # # #

        adv = Signal()
        vtg = self.vtg_sink
        frame_start = Signal()                                          # First active pixel of a frame.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            frame_start.eq(vtg.de & (vtg.hcount == 0) & (vtg.vcount == 0)),
        ]
        take = Signal()                                                 # Pull a pixel this beat.
        drop = Signal()                                                 # Discard the head pixel.
        vblank = Signal()
        self.comb += vblank.eq(vtg.valid & ~vtg.de & (vtg.vcount >= vtg.vres))
        self.fsm = fsm = FSM(reset_state="SYNC")
        fsm.act("SYNC",
            vtg.ready.eq(adv),
            # Drop stale pixels; hold a 'first' pixel until the timing's frame start pulls it.
            drop.eq(adv & ~self.sink.first),
            self.sink.ready.eq(drop | (adv & vtg.valid & frame_start & self.sink.first)),
            If(vtg.valid & adv & frame_start & self.sink.valid & self.sink.first,
                take.eq(1),
                NextState("RUN"),
            ),
        )
        fsm.act("RUN",
            self.synced.eq(1),
            vtg.ready.eq(adv),
            # Active beats pull pixels; the vertical blanking flushes stale (non-first) pixels
            # so a starved frame recovers by the next one.
            drop.eq(adv & vblank & ~self.sink.first),
            self.sink.ready.eq((adv & vtg.valid & vtg.de) | drop),
            take.eq(vtg.valid & vtg.de),
            If(vtg.valid & adv & frame_start & self.sink.valid & ~self.sink.first,
                NextState("SYNC"),                                      # Lost alignment.
            ),
        )
        have = Signal()
        self.comb += have.eq(self.sink.valid)
        self.sync += [
            If(adv,
                self.source.valid.eq(vtg.valid),
                self.source.hsync.eq(vtg.hsync), self.source.vsync.eq(vtg.vsync), self.source.de.eq(vtg.de),
                If(take & have,
                    self.source.r.eq(self.sink.r), self.source.g.eq(self.sink.g), self.source.b.eq(self.sink.b),
                ).Else(
                    self.source.r.eq(0), self.source.g.eq(0), self.source.b.eq(0),
                ),
                If(vtg.valid & fsm.ongoing("RUN") & vtg.de & ~have,
                    self.underflow.eq(1), self.underflows.eq(self.underflows + 1),
                ),
                If(drop & self.sink.valid, self.dropped.eq(self.dropped + 1)),
            ),
            If(self.clear, self.underflow.eq(0)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the underflow flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("underflow", size=1, offset=0, description="Sticky: an active beat had no pixel."),
            CSRField("synced",    size=1, offset=1, description="Pixels are locked to the timing."),
        ])
        self._underflows = CSRStatus(32, name="underflows", description="Active beats without a pixel.")
        self._dropped    = CSRStatus(32, name="dropped", description="Pixels dropped while synchronising.")
        self.comb += [
            self.clear.eq(self._control.fields.clear),
            self._status.fields.underflow.eq(self.underflow), self._status.fields.synced.eq(self.synced),
            self._underflows.status.eq(self.underflows), self._dropped.status.eq(self.dropped),
        ]

    def add_irq(self):
        self.ev = EventManager()
        self.ev.underflow = EventSourcePulse(description="An active video beat had no pixel.")
        self.ev.finalize()
        self.comb += self.ev.underflow.trigger.eq(self.underflow)
