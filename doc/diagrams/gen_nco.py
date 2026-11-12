#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# NCO: phase increment register, phase accumulator, top phase bits addressing the cos/sin ROMs,
# I/Q output; the accumulator advances only when the output can accept a sample.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    reg = d.add(Box(15,  20,  120, 50, label="phase_inc\nregister"))
    acc = d.add(Box(175, 105, 125, 56, label="Phase\naccumulator", fill=COLOR_ACCENT))
    top = d.add(Box(335, 105, 105, 56, label="Top phase\nbits"))
    cos = d.add(Box(480, 60,  110, 46, label="cos ROM", fill=COLOR_ACCENT_LIGHT))
    sin = d.add(Box(480, 160, 110, 46, label="sin ROM", fill=COLOR_ACCENT_LIGHT))
    out = d.add(Box(630, 105, 115, 56, label="I/Q source"))
    d.add(Arrow((reg, "b"), (acc, "l"), kind="control", label="increment",
        label_pos=(83, 150), label_anchor="end"))
    d.add(Arrow((acc, "r"), (top, "l"), kind="accent"))
    d.add(Arrow((top.x + top.w, 120), (cos, "l"), kind="accent", via=[(460, 120), (460, cos.cy)]))
    d.add(Arrow((top.x + top.w, 146), (sin, "l"), kind="accent", via=[(460, 146), (460, sin.cy)]))
    d.add(Arrow((cos, "r"), (out.x, 120), kind="data", via=[(610, cos.cy), (610, 120)],
        label="I", label_pos=(605, 75)))
    d.add(Arrow((sin, "r"), (out.x, 146), kind="data", via=[(610, sin.cy), (610, 146)],
        label="Q", label_pos=(605, 200)))
    d.add(Arrow((out, "b"), (acc, "b"), kind="feedback", via=[(out.cx, 232), (acc.cx, 232)],
        label="advance on ready", label_pos=(390, 226)))
    return d
