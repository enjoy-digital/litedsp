#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# The registry feeds every tool: datasheets, flow, generator, GUI and host drivers.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    blocks = d.add(Box(20, 105, 140, 40, label="Blocks (litedsp/)"))
    reg    = d.add(Box(260, 20, 130, 210, label="Registry", fill=COLOR_ACCENT))
    names  = ["Datasheets", "Flow", "Generator", "GUI", "Host drivers"]
    outs   = ["doc/blocks/", "chain Verilog, IP", "standalone core", "netlists, live mode", "litedsp_cli"]
    d.add(Arrow((blocks, "r"), (reg, "l", (125 - 20)/210), kind="data", label="reflect"))
    for k, (n, o) in enumerate(zip(names, outs)):
        y   = 20 + k*44
        box = d.add(Box(470, y, 120, 34, label=n, fill=COLOR_ACCENT_LIGHT))
        d.add(Arrow((reg.x + reg.w, y + 17), (box, "l"), kind="data"))
        d.add(Text(605, y + 17, o, size=FONT_SIZE_SM, anchor="start"))
    return d
