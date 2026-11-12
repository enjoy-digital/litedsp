#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# One I2S frame: LRCK selects the slot, the sample is MSB first one BCLK after the edge.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 150)
    d.add(Text(70, 45, "LRCK", anchor="end"))
    d.add(Text(70, 100, "SDATA", anchor="end"))
    d.add(Box(90, 30, 325, 30, label="low: left slot", radius=0))
    d.add(Box(415, 30, 325, 30, label="high: right slot", radius=0))
    x = 90
    for half in range(2):
        cells = [(25, "", COLOR_SHADE), (60, "MSB", COLOR_ACCENT), (130, "sample bits", COLOR_ACCENT_LIGHT),
                 (60, "LSB", COLOR_ACCENT), (50, "pad", COLOR_SHADE)]
        for w, lab, fill in cells:
            d.add(Box(x, 85, w, 30, label=lab, radius=0, fill=fill))
            x += w
    d.add(Text(102, 132, "one BCLK", size=FONT_SIZE_SM, anchor="start"))
    return d
