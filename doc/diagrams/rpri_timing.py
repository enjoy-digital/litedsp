#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Pulse timing: a transmit pulse at the start of each PRI, a receive window, M PRIs per CPI.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 190)
    y, h, pri_w = 55, 40, 230
    starts = [20, 250, 520]
    for p, x in enumerate(starts):
        d.add(Box(x, y, 40, h, label="Tx", radius=0, fill=COLOR_ACCENT))
        d.add(Box(x + 40, y, pri_w - 40, h, label="Receive window", radius=0))
        d.add(Arrow((x, 35), (x + pri_w, 35), kind="control", heads="both"))
        d.add(Text(x + pri_w/2, 18, ["PRI 0", "PRI 1", "PRI M-1"][p], size=13))
    d.add(Text(500, y + h/2, "...", size=15))
    d.add(Arrow((60, 115), (250, 115), kind="control"))
    d.add(Text(155, 130, "range bins 0 to N-1", size=13))
    d.add(Arrow((20, 155), (750, 155), kind="control", heads="both"))
    d.add(Text(385, 175, "CPI: M pulses", size=13))
    return d
