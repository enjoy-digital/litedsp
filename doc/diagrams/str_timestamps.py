#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Timestamps at the edges: the time core count is latched at ingress and in the packet header.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 190)
    names = ["ADC", "Timestamper", "Untagger", "Mixer", "Gain", "FIR", "Packetizer", "Host"]
    lats  = ["", "latency 0", "latency 0", "latency 2", "latency 1", "latency 3", "", ""]
    boxes = []
    for k, n in enumerate(names):
        fill = COLOR_HARDWARE if n in ("ADC", "Host") else (COLOR_ACCENT if n in ("Timestamper", "Packetizer") else COLOR_FILL)
        boxes.append(d.add(Box(10 + k*93, 110, 84, 40, label=n, fill=fill, size=12)))
        if lats[k]:
            d.add(Text(10 + k*93 + 42, 168, lats[k], size=FONT_SIZE_SM))
    for a, b in zip(boxes, boxes[1:]):
        d.add(Arrow((a, "r"), (b, "l"), kind="accent" if a is not boxes[0] else "data"))
    core = d.add(Box(boxes[1].x, 20, boxes[6].x + 84 - boxes[1].x, 40, label="LiteDSPTimeCore (64-bit count)",
        fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((boxes[1].cx, 60), (boxes[1], "t"), label="time", label_side="right"))
    d.add(Arrow((boxes[6].cx, 60), (boxes[6], "t"), label="time", label_side="right"))
    return d
