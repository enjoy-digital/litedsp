#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# AN009 setup: RTL FOC and PWM around a per-unit PMSM model, three angle sources.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 330)
    foc = d.add(Box(20,  40, 140, 56, label="LiteDSPFOC", fill=COLOR_ACCENT))
    pwm = d.add(Box(220, 40, 140, 56, label="LiteDSPPWM", fill=COLOR_ACCENT))
    pl  = d.add(Box(430, 40, 160, 56, label="PMSM model", fill=COLOR_HARDWARE))
    d.add(Container(200, 120, 540, 200, title="Angle source, one per build", title_pos="bl"))
    ide = d.add(Box(220, 135, 150, 40, label="Ideal (model)", fill=COLOR_SHADE))
    enc = d.add(Box(220, 185, 150, 40, label="Quadrature\ndecoder", fill=COLOR_ACCENT_LIGHT))
    mux = d.add(Box(220, 245, 150, 40, label="Channel mux"))
    rmp = d.add(Box(600, 260, 120, 36, label="Angle ramp", fill=COLOR_ACCENT_LIGHT))
    smo = d.add(Box(410, 215, 180, 36, label="Observer, tracker", fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((foc, "r"), (pwm, "l"), kind="data", label="duties"))
    d.add(Arrow((pwm, "r"), (pl, "l"), kind="data"))
    d.add(Arrow((pl.cx, pl.y), (foc.cx, foc.y), via=[(pl.cx, 18), (foc.cx, 18)], kind="feedback",
        label="currents", label_pos=(300, 10)))
    d.add(Arrow((pl.x + pl.w - 20, pl.y + pl.h), (smo.x + smo.w - 20, smo.y), via=[],
        kind="feedback", label="i, v", label_pos=(pl.x + pl.w, 160)))
    d.add(Arrow((pl.x + 40, pl.y + pl.h), (enc.x + enc.w, enc.cy), via=[(pl.x + 40, enc.cy)], kind="feedback",
        label="A/B", label_pos=(pl.x + 62, 165)))
    d.add(Arrow((smo, "l"), (mux.x + mux.w, mux.cy - 8), via=[(390, smo.cy), (390, mux.cy - 8)], kind="data"))
    d.add(Arrow((rmp, "l"), (mux.x + mux.w, mux.cy + 8), via=[(390, rmp.cy), (390, mux.cy + 8)], kind="data"))
    for b in (ide, enc, mux):
        d.add(Arrow((b, "l"), (foc.cx, foc.y + foc.h), via=[(foc.cx, b.cy)], kind="data"))
    d.add(Text(foc.cx + 30, 120, "angle", size=FONT_SIZE_SM))
    return d
