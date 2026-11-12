#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Decimation filters before dropping samples (anti-alias); interpolation inserts samples then
# filters (anti-image). Rates on the arrows.

from pri_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 300)
    c1 = d.add(Container(20, 15, 720, 125, title="Decimation by R", title_pos="tl"))
    c2 = d.add(Container(20, 160, 720, 125, title="Interpolation by R", title_pos="tl"))
    f1 = d.add(Box(230, 60, 150, 50, label="Low-pass filter", fill=COLOR_ACCENT))
    k1 = d.add(Box(480, 60, 150, 50, label="Keep 1 of R"))
    d.add(Arrow((60, f1.cy), (f1, "l"), kind="data", label="fs", label_pos=(140, f1.cy - 14)))
    d.add(Arrow((f1, "r"), (k1, "l"), kind="data", label="fs", label_pos=(430, f1.cy - 14)))
    d.add(Arrow((k1, "r"), (720, k1.cy), kind="data", label="fs/R", label_pos=(675, k1.cy - 14)))
    k2 = d.add(Box(230, 205, 150, 50, label="Insert R-1 zeros"))
    f2 = d.add(Box(480, 205, 150, 50, label="Low-pass filter", fill=COLOR_ACCENT))
    d.add(Arrow((60, k2.cy), (k2, "l"), kind="data", label="fs", label_pos=(140, k2.cy - 14)))
    d.add(Arrow((k2, "r"), (f2, "l"), kind="data", label="R fs", label_pos=(430, k2.cy - 14)))
    d.add(Arrow((f2, "r"), (720, f2.cy), kind="data", label="R fs", label_pos=(675, f2.cy - 14)))
    return d
