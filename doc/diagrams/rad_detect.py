#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Radar detection back end: Doppler processor, 2-D CFAR, peak extractor, target list and
# tracker, with the stream kind between each pair.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 220)
    y, h = 45, 50
    dop  = d.add(Box(10, y, 110, h, label="Doppler\nprocessor", fill=COLOR_ACCENT))
    cfar = d.add(Box(170, y, 100, h, label="2-D CFAR", fill=COLOR_ACCENT))
    peak = d.add(Box(320, y, 110, h, label="Peak\nextractor", fill=COLOR_ACCENT_LIGHT))
    tl   = d.add(Box(490, y, 100, h, label="Target list", fill=COLOR_ACCENT_LIGHT))
    trk  = d.add(Box(490, 145, 100, h, label="Tracker", fill=COLOR_ACCENT_LIGHT))
    host = d.add(Box(650, y, 95, h, label="Host", fill=COLOR_HARDWARE))
    d.add(Arrow((dop, "r"), (cfar, "l"), kind="data", label="map", label_pos=(145, 35)))
    d.add(Arrow((cfar, "r"), (peak, "l"), kind="data", label="cell", label_pos=(295, 35)))
    d.add(Arrow((peak, "r"), (tl, "l"), kind="data", label="target", label_pos=(460, 35)))
    d.add(Arrow((peak, "b"), (trk, "l"), kind="data", via=[(peak.cx, trk.cy)]))
    d.add(Text(400, 182, "target", size=12))
    d.add(Text(peak.cx + 22, 120, "split", size=12))
    d.add(Arrow((tl, "r"), (host, "l"), kind="control", label="registers", label_pos=(620, 35)))
    d.add(Arrow((trk, "r"), (host, "b"), kind="data", via=[(host.cx, trk.cy)]))
    d.add(Text(650, 182, "track", size=12))
    return d
