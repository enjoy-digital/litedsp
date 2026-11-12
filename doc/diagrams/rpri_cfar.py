#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# One-dimensional CFAR window: training cells on both sides, guard cells, cell under test,
# threshold = alpha times the training mean.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 260)
    y, cw, ch = 45, 50, 40
    kinds = ["T", "T", "T", "G", "C", "G", "T", "T", "T"]
    x0 = 155
    cells = []
    for i, k in enumerate(kinds):
        fill  = {"T": COLOR_ACCENT_LIGHT, "G": COLOR_SHADE, "C": COLOR_ACCENT}[k]
        label = {"T": "train", "G": "guard", "C": "CUT"}[k]
        cells.append(d.add(Box(x0 + i*cw, y, cw, ch, label=label, radius=0, fill=fill, size=13)))
    mean  = d.add(Box(315, 125, 130, 40, label="Training mean"))
    alpha = d.add(Box(315, 200, 130, 40, label="x alpha", fill=COLOR_ACCENT))
    cmp_  = d.add(Box(540, 200, 120, 40, label="Compare", fill=COLOR_ACCENT))
    d.add(Arrow((cells[1], "b"), (mean, "t", 0.25), kind="control", via=[(cells[1].cx, 105),
        (mean.x + mean.w*0.25, 105)]))
    d.add(Arrow((cells[7], "b"), (mean, "t", 0.75), kind="control", via=[(cells[7].cx, 105),
        (mean.x + mean.w*0.75, 105)]))
    d.add(Arrow((mean, "b"), (alpha, "t"), kind="data"))
    d.add(Arrow((alpha, "r"), (cmp_, "l"), kind="data", label="threshold", label_pos=(492, 208)))
    d.add(Arrow((cells[4], "t"), (cmp_, "r"), kind="control", via=[(cells[4].cx, 20), (720, 20),
        (720, 220)]))
    d.add(Text(cells[4].cx + 15, 32, "cell under test", size=12, anchor="start"))
    return d
