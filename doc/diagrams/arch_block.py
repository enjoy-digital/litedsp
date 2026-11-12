#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Anatomy of a block: endpoints, datapath, control signals, registers and the bypass path.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 265)
    d.add(Container(110, 10, 545, 245, title="block", title_pos="br"))
    bus   = d.add(Box(10,  30, 80, 46, label="CSR bus", fill=COLOR_HARDWARE))
    regs  = d.add(Box(130, 30, 120, 46, label="Registers\nadd_csr()"))
    ctrl  = d.add(Box(300, 30, 140, 46, label="Control signals"))
    dp    = d.add(Box(300, 110, 140, 50, label="Datapath", fill=COLOR_ACCENT))
    byp   = d.add(Box(300, 185, 140, 50, label="Bypass delay\ndata + select", fill=COLOR_ACCENT_LIGHT))
    mux   = d.add(Box(530, 110, 60, 125, label="Mux"))
    up    = d.add(Box(10, 115, 80, 40, label="Previous"))
    down  = d.add(Box(670, 147, 80, 40, label="Next block"))
    d.add(Arrow((bus, "r"), (regs, "l"), heads="both"))
    d.add(Arrow((regs, "r"), (ctrl, "l")))
    d.add(Arrow((ctrl, "b"), (dp, "t")))
    d.add(Arrow((ctrl, "r"), (420, 185), via=[(470, 53), (470, 172), (420, 172)], label="bypass",
        label_pos=(478, 100), label_anchor="start"))
    d.add(Arrow((up, "r"), (dp, "l"), kind="accent", label="sink"))
    d.add(Arrow((270, 135), (byp, "l"), via=[(270, 210)], kind="data"))
    d.add(Arrow((dp, "r"), (mux, "l", 25/125), kind="accent"))
    d.add(Arrow((byp, "r"), (mux, "l", 100/125), kind="data"))
    d.add(Arrow((mux, "r", 57/125), (down, "l"), kind="accent", label="source"))
    return d
