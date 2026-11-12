#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# AN010 chain: I2S in, EQ, compressor, limiter, volume, peak meter, dither, I2S out.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 110)
    names = [("I2S RX", COLOR_ACCENT_LIGHT), ("EQ", COLOR_ACCENT), ("Comp.", COLOR_ACCENT),
             ("Limiter", COLOR_ACCENT), ("Volume", COLOR_ACCENT), ("Peak\nmeter", COLOR_ACCENT),
             ("Dither", COLOR_ACCENT), ("I2S TX", COLOR_ACCENT_LIGHT)]
    boxes = []
    for k, (n, f) in enumerate(names):
        boxes.append(d.add(Box(10 + k*94, 25, 74, 56, label=n, fill=f)))
    for a, b in zip(boxes, boxes[1:]):
        d.add(Arrow((a, "r"), (b, "l"), kind="data"))
    return d
