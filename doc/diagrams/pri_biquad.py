#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Transposed direct form II biquad: the output is b0 x plus the first state; each state register
# holds a sum of feed-forward (b) and feedback (a) products of the newest x and y.

from pri_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 360)
    t0 = d.add(Box(260, 30, 200, 50, label="Tap 0: b0", fill=COLOR_ACCENT))
    t1 = d.add(Box(260, 150, 200, 50, label="Tap 1: b1, -a1", fill=COLOR_ACCENT_LIGHT))
    t2 = d.add(Box(260, 270, 200, 50, label="Tap 2: b2, -a2", fill=COLOR_ACCENT_LIGHT))
    z1 = d.add(Box(320, 95, 80, 40, label="z-1"))
    z2 = d.add(Box(320, 215, 80, 40, label="z-1"))
    rs = d.add(Box(530, 30, 130, 50, label="Round, saturate"))
    d.add(Arrow((z1, "t"), (t0, "b"), kind="data", label="s1", label_pos=(410, 115), label_anchor="start"))
    d.add(Arrow((t1, "t"), (z1, "b"), kind="data"))
    d.add(Arrow((z2, "t"), (t1, "b"), kind="data", label="s2", label_pos=(410, 235), label_anchor="start"))
    d.add(Arrow((t2, "t"), (z2, "b"), kind="data"))
    # Input x feeds the three taps.
    d.add(Bus([(80, 55), (80, 295)], kind="data"))
    d.add(Arrow((30, 55), (t0, "l"), kind="data", label="x[n]", label_pos=(50, 41)))
    d.add(Arrow((80, 175), (t1, "l"), kind="data"))
    d.add(Arrow((80, 295), (t2, "l"), kind="data"))
    d.add(Arrow((t0, "r"), (rs, "l"), kind="data"))
    d.add(Arrow((rs, "r"), (740, rs.cy), kind="data", label="y[n]", label_pos=(705, 41)))
    # Rounded output y feeds back to taps 1 and 2.
    d.add(Arrow((700, 55), (t1, "r"), via=[(700, 175)], kind="feedback"))
    d.add(Arrow((700, 175), (t2, "r"), via=[(700, 295)], kind="feedback"))
    return d
