#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# 3x3 neighbourhood operation: the window around a pixel times a kernel, summed and rescaled.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 240)
    x0, y0, c = 30, 30, 34
    for r in range(5):
        for k in range(6):
            inwin = 1 <= r <= 3 and 1 <= k <= 3
            centre = r == 2 and k == 2
            fill = COLOR_ACCENT if centre else (COLOR_ACCENT_LIGHT if inwin else COLOR_FILL)
            d.add(Box(x0 + k*c, y0 + r*c, c, c, radius=0, fill=fill))
    d.add(Text(x0 + 3*c, y0 + 5*c + 20, "image, window around p", size=13))
    kx = 300
    coef = [1, 2, 1, 2, 4, 2, 1, 2, 1]
    for i, v in enumerate(coef):
        d.add(Box(kx + (i % 3)*c, y0 + c + (i//3)*c, c, c, label=str(v), radius=0,
            fill=COLOR_ACCENT_LIGHT, size=13))
    d.add(Text(kx + 1.5*c, y0 + 5*c + 20, "kernel", size=13))
    d.add(Arrow((x0 + 6*c, y0 + 2.5*c), (kx, y0 + 2.5*c), kind="data"))
    s = d.add(Box(480, y0 + 1.5*c, 120, 2*c, label="Sum of\nproducts,\nshift", fill=COLOR_ACCENT))
    d.add(Arrow((kx + 3*c, y0 + 2.5*c), (s, "l"), kind="data"))
    o = d.add(Box(650, y0 + 2*c, 80, c, label="p out"))
    d.add(Arrow((s, "r"), (o, "l"), kind="data"))
    return d
