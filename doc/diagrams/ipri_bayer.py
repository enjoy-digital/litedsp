#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Bayer mosaic (RGGB): one colour per photosite; demosaicing interpolates the two missing ones.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 230)
    x0, y0, cw = 40, 30, 40
    names = {0: "R", 1: "G", 2: "B"}
    phase = (0, 1, 1, 2)
    for r in range(4):
        for c in range(4):
            k = phase[2*(r & 1) + (c & 1)]
            fill = {0: COLOR_ACCENT, 1: COLOR_ACCENT_LIGHT, 2: COLOR_SHADE}[k]
            d.add(Box(x0 + c*cw, y0 + r*cw, cw, cw, label=names[k], radius=0, fill=fill))
    d.add(Text(x0 + 2*cw, y0 + 4*cw + 20, "raw mosaic, one code", size=13))
    deb = d.add(Box(300, 85, 150, 50, label="Demosaic\n(interpolate)", fill=COLOR_ACCENT))
    d.add(Arrow((x0 + 4*cw, 110), (deb, "l"), kind="data", label="mono", label_pos=(240, 98)))
    out = d.add(Box(560, 85, 140, 50, label="RGB pixels"))
    d.add(Arrow((deb, "r"), (out, "l"), kind="data"))
    d.add(Text(630, 160, "one stream, three codes per pixel", size=13))
    return d
