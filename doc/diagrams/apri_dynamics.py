#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Dynamics processor: side chain (detector, log gain computer, smoother) and the main path.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 220)
    inp  = d.add(Box(20,  130, 90, 50, label="Input"))
    dly  = d.add(Box(240, 130, 130, 50, label="Lookahead\ndelay", fill=COLOR_ACCENT_LIGHT))
    mul  = d.add(Box(520, 130, 90, 50, label="Gain", fill=COLOR_ACCENT))
    out  = d.add(Box(660, 130, 80, 50, label="Output"))
    det  = d.add(Box(150, 30, 110, 50, label="Level\ndetector", fill=COLOR_ACCENT_LIGHT))
    gc   = d.add(Box(300, 30, 120, 50, label="Gain\ncomputer", fill=COLOR_ACCENT))
    sm   = d.add(Box(460, 30, 120, 50, label="Attack,\nrelease", fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((inp, "r"), (dly, "l"), kind="data"))
    d.add(Arrow((dly, "r"), (mul, "l"), kind="data"))
    d.add(Arrow((mul, "r"), (out, "l"), kind="data"))
    d.add(Arrow((inp.cx, inp.y), (det, "l")))
    d.add(Arrow((det, "r"), (gc, "l"), label="dB"))
    d.add(Arrow((gc, "r"), (sm, "l")))
    d.add(Arrow((sm.x + 90, sm.y + sm.h), (sm.x + 90, mul.y)))
    return d
