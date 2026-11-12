#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Target burst: per CPI, the records (hit = 1) then one terminator (hit = 0, data = count);
# an empty CPI is a single terminator with first and last.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 200)
    y, h, w = 40, 44, 120
    x0 = 160
    cells = [("record 0\nhit = 1", COLOR_ACCENT_LIGHT), ("record 1\nhit = 1", COLOR_ACCENT_LIGHT),
        ("record 2\nhit = 1", COLOR_ACCENT_LIGHT), ("terminator\nhit = 0", COLOR_ACCENT)]
    for i, (label, fill) in enumerate(cells):
        d.add(Box(x0 + i*w, y, w, h, label=label, radius=0, fill=fill, size=13))
    d.add(Text(140, y + h/2, "CPI with\n3 targets", size=13, anchor="end"))
    d.add(Text(x0 + w/2, y + h + 15, "first", size=12))
    d.add(Text(x0 + 3.5*w, y + h + 15, "last, data = 3", size=12))
    y2 = 125
    d.add(Box(x0, y2, w, h, label="terminator\nhit = 0", radius=0, fill=COLOR_ACCENT, size=13))
    d.add(Text(140, y2 + h/2, "empty CPI", size=13, anchor="end"))
    d.add(Text(x0 + w + 15, y2 + h/2, "first and last, data = 0", size=12, anchor="start"))
    return d
