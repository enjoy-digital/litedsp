#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Raster scan of a frame: pixels left to right, lines top to bottom; first, eol and last tags.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    x0, y0, cw, ch = 150, 50, 55, 34
    rows, cols = 5, 8
    for r in range(rows):
        for c in range(cols):
            label, fill = "", COLOR_FILL
            if r == 0 and c == 0:
                label, fill = "first", COLOR_ACCENT
            elif r == rows - 1 and c == cols - 1:
                label, fill = "last", COLOR_ACCENT
            elif c == cols - 1:
                label, fill = "eol", COLOR_ACCENT_LIGHT
            d.add(Box(x0 + c*cw, y0 + r*ch, cw, ch, label=label, radius=0, fill=fill, size=13))
    d.add(Arrow((x0, 30), (x0 + cols*cw, 30), kind="data"))
    d.add(Text(x0 + cols*cw/2, 15, "pixels of a line: col 0 to width-1", size=13))
    d.add(Arrow((x0 - 25, y0), (x0 - 25, y0 + rows*ch), kind="data"))
    d.add(Text(x0 - 35, y0 + rows*ch/2, "lines:\nrow 0 to\nheight-1", size=13, anchor="end"))
    d.add(Text(x0 + cols*cw + 15, y0 + rows*ch - ch/2, "end of frame", size=13, anchor="start"))
    d.add(Text(x0 + cols*cw + 15, y0 + ch/2, "end of line", size=13, anchor="start"))
    return d
