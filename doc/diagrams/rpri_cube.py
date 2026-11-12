#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Radar data matrix: rows are pulses (slow time), columns are range bins (fast time); the
# corner turn reads one column per range bin.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 280)
    x0, y0, cw, ch = 170, 60, 50, 36
    rows, cols, hl = 5, 8, 3
    for r in range(rows):
        for c in range(cols):
            fill = COLOR_ACCENT if c == hl else COLOR_FILL
            d.add(Box(x0 + c*cw, y0 + r*ch, cw, ch, radius=0, fill=fill))
    for r, name in enumerate(["pulse 0", "pulse 1", "pulse 2", "...", "pulse M-1"]):
        d.add(Text(x0 - 12, y0 + r*ch + ch/2, name, size=13, anchor="end"))
    d.add(Arrow((x0, 40), (x0 + cols*cw, 40), kind="data"))
    d.add(Text(x0 + cols*cw/2, 22, "fast time: range bin 0 to N-1", size=13))
    xr = x0 + cols*cw + 25
    d.add(Arrow((xr, y0), (xr, y0 + rows*ch), kind="data"))
    d.add(Text(xr + 12, y0 + rows*ch/2, "slow time:\nM pulses", size=13, anchor="start"))
    d.add(Text(x0 + hl*cw + cw/2, y0 + rows*ch + 25, "one slow-time column", size=13))
    return d
