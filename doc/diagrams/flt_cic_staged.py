#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Staged CIC decimator: elastic integrator stages at the input rate, a marked sample every R-th
# input, elastic comb stages at the output rate, round and saturate.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 220)
    inp = d.add(Box(10,  60, 80,  56, label="Input\nI/Q"))
    itg = d.add(Box(115, 60, 120, 56, label="Integrators\nN stages", fill=COLOR_ACCENT, stack=2))
    rat = d.add(Box(270, 60, 110, 56, label="Keep the\nmarked sample"))
    cmb = d.add(Box(410, 60, 120, 56, label="Combs\nN stages", fill=COLOR_ACCENT, stack=2))
    rsc = d.add(Box(565, 60, 95,  56, label="Round,\nsaturate"))
    out = d.add(Box(680, 60, 70,  56, label="Output"))
    cnt = d.add(Box(115, 155, 120, 50, label="Phase\ncounter"))
    d.add(Arrow((inp, "r"), (itg, "l"), kind="data"))
    d.add(Arrow((itg.x + itg.w + 8, itg.cy), (rat, "l"), kind="accent"))
    d.add(Arrow((rat, "r"), (cmb, "l"), kind="accent", label="1 in R", label_pos=(395, 48)))
    d.add(Arrow((cmb.x + cmb.w + 8, cmb.cy), (rsc, "l"), kind="accent"))
    d.add(Arrow((rsc, "r"), (out, "l"), kind="data"))
    d.add(Arrow((cnt, "t"), (itg, "b"), kind="control", label="emit mark", label_pos=(182, 140),
        label_anchor="start"))
    return d
