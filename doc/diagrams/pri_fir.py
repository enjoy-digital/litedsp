#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Three-tap FIR filter: a delay line holds the last samples, each tap multiplies one sample by its
# coefficient, an adder tree sums the products, and the sum is rounded and saturated.

from pri_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 330)
    z1 = d.add(Box(230, 30, 90, 44, label="z-1"))
    z2 = d.add(Box(430, 30, 90, 44, label="z-1"))
    xs = [130, 330, 530]
    ms = [d.add(Box(x - 55, 130, 110, 44, label=f"x c{k}", fill=COLOR_ACCENT_LIGHT))
        for k, x in enumerate(xs)]
    add = d.add(Box(75, 230, 510, 44, label="Adder tree", fill=COLOR_ACCENT))
    rs  = d.add(Box(615, 230, 120, 44, label="Round, saturate"))
    d.add(Arrow((20, z1.cy), (z1, "l"), kind="data", label="x[n]", label_pos=(45, z1.cy - 14)))
    d.add(Arrow((z1, "r"), (z2, "l"), kind="data"))
    d.add(Arrow((xs[0], z1.cy), (ms[0], "t"), kind="data"))
    d.add(Arrow((xs[1], z1.cy), (ms[1], "t"), kind="data"))
    d.add(Arrow((z2, "r"), (xs[2], z2.cy), via=[], kind="data", heads="none"))
    d.add(Arrow((xs[2], z2.cy), (ms[2], "t"), kind="data"))
    for m in ms:
        d.add(Arrow((m, "b"), (m.cx, add.y), kind="data"))
    d.add(Arrow((add, "r"), (rs, "l"), kind="data"))
    d.add(Arrow((rs, "b"), (rs.cx, 315), kind="data", label="y[n]", label_pos=(rs.cx + 10, 300),
        label_anchor="start"))
    return d
