#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Polyphase decimator: a commutator deals the input samples to R sub-filters (taps c[p::R]) that
# each run at the output rate; their outputs add up to one output sample.

from pri_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 290)
    com = d.add(Box(110, 95, 130, 90, label="Commutator"))
    ys  = [30, 115, 200]
    names = ["Sub-filter 0\nc[0::R]", "Sub-filter 1\nc[1::R]", "Sub-filter R-1\nc[R-1::R]"]
    subs = [d.add(Box(320, y, 160, 54, label=n, fill=COLOR_ACCENT)) for y, n in zip(ys, names)]
    add = d.add(Box(560, 95, 80, 90, label="Sum"))
    d.add(Arrow((20, com.cy), (com, "l"), kind="data", label="fs", label_pos=(60, com.cy - 14)))
    for s, f in zip(subs, (0.2, 0.5, 0.8)):
        d.add(Arrow((com, "r", f), (s, "l"), kind="data"))
        d.add(Arrow((s, "r"), (add, "l", f), kind="data"))
    d.add(Arrow((add, "r"), (740, add.cy), kind="data", label="fs/R", label_pos=(695, add.cy - 14)))
    return d
