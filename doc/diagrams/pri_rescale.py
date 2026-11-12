#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Rescaling a Q1.15 x Q1.15 product back to Q1.15: add half an output LSB, shift right by 15
# (rounded), then clamp to the 16-bit range (saturated); scaled() also returns an overflow flag.

from pri_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    d.add(Container(200, 15, 270, 130, title="rounded()", title_pos="tl"))
    d.add(Container(490, 15, 150, 130, title="saturated()", title_pos="tl"))
    m  = d.add(Box(30, 65, 120, 50, label="Multiply"))
    a  = d.add(Box(220, 65, 110, 50, label="Add half LSB", fill=COLOR_ACCENT))
    s  = d.add(Box(350, 65, 100, 50, label="Shift by 15", fill=COLOR_ACCENT))
    c  = d.add(Box(510, 65, 110, 50, label="Clamp", fill=COLOR_ACCENT))
    d.add(Arrow((m, "r"), (a, "l"), kind="data", label="Q2.30", label_pos=(175, m.cy - 14)))
    d.add(Arrow((a, "r"), (s, "l"), kind="data"))
    d.add(Arrow((s, "r"), (c, "l"), kind="data"))
    d.add(Arrow((c, "r"), (740, c.cy), kind="data", label="Q1.15", label_pos=(690, c.cy - 14)))
    d.add(Arrow((10, 80), (m, "l", 0.3), kind="data"))
    d.add(Arrow((10, 100), (m, "l", 0.7), kind="data"))
    d.add(Text(4, 48, "two Q1.15", size=12, anchor="start"))
    d.add(Arrow((c, "b"), (c.cx, 215), kind="control", label="overflow (scaled)", label_pos=(c.cx + 10, 200),
        label_anchor="start"))
    return d
