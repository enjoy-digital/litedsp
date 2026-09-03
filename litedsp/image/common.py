#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Shared image helpers: the pixel coordinate counter."""

from migen import *

from litex.gen import *

from litedsp.common import check

# Pixel Counter ------------------------------------------------------------------------------------

class LiteDSPPixelCounter(LiteXModule):
    """Derive pixel coordinates and the frame geometry from the stream tags.

    Drive ``xfer`` (an accepted beat) with the beat's ``first``, ``eol`` and ``last``: ``col`` /
    ``row`` are the coordinates of that beat (``first`` re-synchronises them to 0,0
    unconditionally, reset counts as a frame start), ``width`` is learned at the first ``eol``
    (``width_valid``) and ``height`` at ``last``. Consumers derive, producers configure: a
    block never needs a width to count pixels, only to size line buffers (``max_width``) or to
    cut a raster it generates.
    """
    def __init__(self, coord_bits=12):
        check(4 <= coord_bits <= 16, "expected 4 <= coord_bits <= 16")
        self.xfer  = Signal()
        self.first = Signal()
        self.eol   = Signal()
        self.last  = Signal()
        self.col    = Signal(coord_bits)
        self.row    = Signal(coord_bits)
        self.width  = Signal(coord_bits + 1)
        self.height = Signal(coord_bits + 1)
        self.width_valid  = Signal()
        self.height_valid = Signal()

        # # #

        ncol, nrow = Signal(coord_bits), Signal(coord_bits)             # Coordinates of the next beat.
        self.comb += [
            self.col.eq(Mux(self.first, 0, ncol)),
            self.row.eq(Mux(self.first, 0, nrow)),
        ]
        self.sync += If(self.xfer,
            If(self.eol,
                ncol.eq(0), nrow.eq(self.row + 1),
                If(self.row == 0, self.width.eq(self.col + 1), self.width_valid.eq(1)),   # Every first line.
            ).Else(
                ncol.eq(self.col + 1), nrow.eq(self.row),
            ),
            If(self.last,
                ncol.eq(0), nrow.eq(0),
                self.height.eq(self.row + 1), self.height_valid.eq(1),
            ),
        )
