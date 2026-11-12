#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# The two control modes of a block: registers (with_csr=True) or a parent driving the signals.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 300)
    d.add(Container(10, 10, 360, 280, title="with_csr=True", title_pos="br"))
    d.add(Container(390, 10, 360, 280, title="with_csr=False", title_pos="br"))
    bus  = d.add(Box(40, 30, 170, 40, label="CSR bus", fill=COLOR_HARDWARE))
    regs = d.add(Box(40, 95, 170, 40, label="Registers"))
    sig  = d.add(Box(40, 160, 170, 40, label="Control signals", fill=COLOR_ACCENT))
    dp   = d.add(Box(40, 225, 170, 40, label="Datapath"))
    d.add(Arrow((bus, "b"), (regs, "t"), heads="both"))
    d.add(Arrow((regs, "b"), (sig, "t"), label="add_csr()", label_side="right"))
    d.add(Arrow((sig, "b"), (dp, "t")))
    par  = d.add(Box(420, 95, 170, 40, label="Parent or test"))
    sig2 = d.add(Box(420, 160, 170, 40, label="Control signals", fill=COLOR_ACCENT))
    dp2  = d.add(Box(420, 225, 170, 40, label="Datapath"))
    d.add(Arrow((par, "b"), (sig2, "t"), label=".eq()", label_side="right"))
    d.add(Arrow((sig2, "b"), (dp2, "t")))
    return d
