#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Camera front end: video in, demosaic, white balance, colour matrix, 2-D filter, threshold,
# with statistics and histogram taps.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 220)
    y, h, w = 40, 50, 90
    names = [("Pixel from\nvideo", COLOR_ACCENT_LIGHT), ("Debayer", COLOR_ACCENT),
        ("Pixel gain", COLOR_ACCENT_LIGHT), ("Pixel stats", COLOR_SHADE), ("Colour\nmatrix", COLOR_ACCENT_LIGHT),
        ("Kernel or\nSobel", COLOR_ACCENT), ("Threshold", COLOR_ACCENT_LIGHT)]
    boxes = [d.add(Box(15 + i*106, y, w, h, label=n, fill=f)) for i, (n, f) in enumerate(names)]
    for a, b in zip(boxes, boxes[1:]):
        d.add(Arrow((a, "r"), (b, "l"), kind="data"))
    hist = d.add(Box(boxes[5].x - 15, 150, 120, 44, label="Histogram"))
    d.add(Arrow((boxes[5], "b"), (hist, "t"), kind="control", label="split", label_pos=(boxes[5].cx + 22, 120)))
    d.add(Text(boxes[0].cx, 20, "raw Bayer", size=12))
    d.add(Text(boxes[4].x - 8, 20, "RGB", size=12))
    d.add(Text(boxes[5].x - 8, 20, "luma", size=12))
    return d
