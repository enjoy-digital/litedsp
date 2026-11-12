#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Pulse-Doppler processing stages: compression, clutter cancellation, Doppler, CFAR, peaks, tracks.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 150)
    names = ["Pulse\ncompression", "Clutter\ncancel", "Doppler\nFFT", "CFAR\ndetection",
        "Peak\nextraction", "Tracking"]
    adc = d.add(Box(10, 50, 60, 50, label="ADC", fill=COLOR_HARDWARE))
    boxes, x = [], 90
    for i, name in enumerate(names):
        fill = COLOR_ACCENT if i in (0, 2, 3) else COLOR_ACCENT_LIGHT
        boxes.append(d.add(Box(x, 50, 95, 50, label=name, fill=fill)))
        x += 112
    d.add(Arrow((adc, "r"), (boxes[0], "l"), kind="data"))
    for a, b in zip(boxes, boxes[1:]):
        d.add(Arrow((a, "r"), (b, "l"), kind="data"))
    d.add(Text(boxes[0].x, 25, "fast time, per pulse", size=13, anchor="start"))
    d.add(Text(boxes[2].x, 25, "slow time, per range bin", size=13, anchor="start"))
    d.add(Text(boxes[4].x, 125, "sparse records, per CPI", size=13, anchor="start"))
    return d
