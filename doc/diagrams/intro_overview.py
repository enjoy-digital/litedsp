#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# A LiteDSP design: converter, frontend, chain of blocks, output block, host; registers on the side.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 240)
    d.add(Container(120, 10, 500, 220, title="FPGA", title_pos="br"))
    d.add(Container(245, 20, 230, 100, title="chain", title_pos="tl", title_size=15, fill="#f6f6f6"))
    adc   = d.add(Box(10,  50, 95, 40, label="Converter", fill=COLOR_HARDWARE))
    fe    = d.add(Box(135, 50, 95, 40, label="Frontend", fill=COLOR_ACCENT_LIGHT))
    b0    = d.add(Box(260, 50, 60, 40, label="DDC", fill=COLOR_ACCENT))
    b1    = d.add(Box(330, 50, 60, 40, label="FIR", fill=COLOR_ACCENT))
    b2    = d.add(Box(400, 50, 60, 40, label="Gain", fill=COLOR_ACCENT))
    out   = d.add(Box(495, 45, 110, 50, label="Capture, DMA\nor UDP", fill=COLOR_ACCENT_LIGHT))
    regs  = d.add(Box(260, 150, 200, 40, label="Registers"))
    host  = d.add(Box(650, 50, 100, 40, label="Host", fill=COLOR_HARDWARE))
    d.add(Arrow((adc, "r"), (fe, "l"), kind="accent"))
    d.add(Arrow((fe, "r"), (b0, "l"), kind="accent"))
    d.add(Arrow((b0, "r"), (b1, "l"), kind="accent"))
    d.add(Arrow((b1, "r"), (b2, "l"), kind="accent"))
    d.add(Arrow((b2, "r"), (out, "l", 0.5), kind="accent"))
    d.add(Arrow((out, "r"), (host, "l"), kind="accent"))
    d.add(Arrow((regs, "t", 0.15), (b0, "b")))
    d.add(Arrow((regs, "t", 0.5), (b1, "b")))
    d.add(Arrow((regs, "t", 0.85), (b2, "b")))
    d.add(Arrow((host, "b"), (regs, "r"), heads="both", label="register bus", label_pos=(700, 160),
        label_anchor="middle"))
    return d
