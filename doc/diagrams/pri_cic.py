#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# CIC decimator and interpolator: N integrators at the high rate, the rate change, N combs at the
# low rate, then the rescale by the CIC gain.

from pri_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 300)
    d.add(Container(15, 10, 730, 130, title="Decimator", title_pos="tl"))
    d.add(Container(15, 160, 730, 130, title="Interpolator", title_pos="tl"))
    i1 = d.add(Box(80, 65, 140, 46, label="N integrators", stack=2, fill=COLOR_ACCENT))
    k1 = d.add(Box(270, 65, 120, 46, label="Keep 1 of R"))
    c1 = d.add(Box(440, 65, 140, 46, label="N combs", stack=2, fill=COLOR_ACCENT))
    r1 = d.add(Box(620, 65, 105, 46, label="Rescale"))
    chain(d, [i1, k1, c1, r1])
    d.add(Arrow((30, i1.cy), (i1, "l"), kind="data"))
    c2 = d.add(Box(80, 215, 140, 46, label="N combs", stack=2, fill=COLOR_ACCENT))
    k2 = d.add(Box(270, 215, 120, 46, label="Insert zeros"))
    i2 = d.add(Box(440, 215, 140, 46, label="N integrators", stack=2, fill=COLOR_ACCENT))
    r2 = d.add(Box(620, 215, 105, 46, label="Rescale"))
    chain(d, [c2, k2, i2, r2])
    d.add(Arrow((30, c2.cy), (c2, "l"), kind="data"))
    return d
