#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# The FOC cascade: speed loop around the current loop.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 230)
    spd  = d.add(Box(20,  40, 100, 56, label="Speed\nregulator"))
    cur  = d.add(Box(180, 40, 100, 56, label="Current\nregulators", fill=COLOR_ACCENT))
    ipk  = d.add(Box(340, 40, 90, 56, label="Inverse\nPark", fill=COLOR_ACCENT_LIGHT))
    mod  = d.add(Box(480, 40, 90, 56, label="Modulator", fill=COLOR_ACCENT_LIGHT))
    inv  = d.add(Box(630, 40, 110, 56, label="Inverter\nand motor", fill=COLOR_HARDWARE))
    park = d.add(Box(340, 150, 90, 56, label="Clarke\nand Park", fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((spd, "r"), (cur, "l"), kind="data", label="i_q"))
    d.add(Arrow((cur, "r"), (ipk, "l"), kind="data", label="v_dq"))
    d.add(Arrow((ipk, "r"), (mod, "l"), kind="data"))
    d.add(Arrow((mod, "r"), (inv, "l"), kind="data", label="duties"))
    d.add(Arrow((inv, "b"), (park, "r"), kind="feedback", label="currents", label_side="right"))
    d.add(Arrow((park, "l"), (cur, "b"), kind="feedback"))
    d.add(Arrow((inv.x + 30, inv.y + inv.h), (inv.x + 30, 125), via=[(inv.x + 30, 125), (spd.cx, 125)],
        kind="feedback", heads="none"))
    d.add(Arrow((spd.cx, 125), (spd, "b"), kind="feedback", label="speed", label_side="right"))
    return d
