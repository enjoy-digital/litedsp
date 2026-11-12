#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Line buffer: K-1 line RAMs and the incoming pixel form a column that shifts into the K x K
# window registers; border muxes driven by the output coordinates.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    top, height = 30, 194
    pin  = d.add(Box(10, 30, 80, 44, label="Pixel"))
    ram1 = d.add(Box(150, 100, 120, 44, label="Line RAM 1", fill=COLOR_ACCENT))
    ram2 = d.add(Box(150, 180, 120, 44, label="Line RAM 2", fill=COLOR_ACCENT))
    win  = d.add(Box(340, top, 120, height, label="Window\nregisters\nK x K", fill=COLOR_ACCENT_LIGHT))
    brd  = d.add(Box(510, top, 110, height, label="Border\nmuxes", fill=COLOR_ACCENT_LIGHT))
    out  = d.add(Box(665, 105, 85, 44, label="Window"))
    frac = lambda y: (y - top)/height
    d.add(Arrow((pin, "r"), (win, "l", frac(pin.cy)), kind="data"))
    d.add(Arrow((110, pin.cy), (ram1, "t"), kind="data", via=[(110, 85), (ram1.cx, 85)]))
    d.add(Arrow((ram1, "r"), (win, "l", frac(ram1.cy)), kind="data"))
    d.add(Arrow((ram1, "b"), (ram2, "t"), kind="data"))
    d.add(Arrow((ram2, "r"), (win, "l", frac(ram2.cy)), kind="data"))
    d.add(Arrow((win, "r"), (brd, "l"), kind="data"))
    d.add(Arrow((brd, "r"), (out, "l"), kind="accent"))
    d.add(Text(305, 20, "column", size=12))
    return d
