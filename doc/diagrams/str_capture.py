#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Ways out of a chain toward the host: triggered capture with CSR or Wishbone readout, DMA to memory.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    chain = d.add(Box(10, 95, 100, 40, label="Chain"))
    cap   = d.add(Box(170, 30, 130, 50, label="Capture\ntrigger, RAM", fill=COLOR_ACCENT))
    dma   = d.add(Box(170, 165, 130, 50, label="DMA capture\npack, write", fill=COLOR_ACCENT))
    rdr   = d.add(Box(360, 30, 120, 50, label="CSR reader"))
    soc   = d.add(Box(360, 105, 120, 40, label="SoC bus"))
    mem   = d.add(Box(360, 170, 120, 40, label="Memory", fill=COLOR_HARDWARE))
    host  = d.add(Box(600, 105, 150, 40, label="Host", fill=COLOR_HARDWARE))
    d.add(Arrow((chain, "r", 0.3), (cap, "l"), kind="accent"))
    d.add(Arrow((chain, "r", 0.7), (dma, "l"), kind="accent"))
    d.add(Arrow((cap, "r"), (rdr, "l"), kind="data", label="source"))
    d.add(Arrow((cap, "b", 0.8), (soc, "l"), kind="control", label="Wishbone", label_pos=(300, 115)))
    d.add(Arrow((rdr, "b"), (soc, "t"), heads="both"))
    d.add(Arrow((dma, "r"), (mem, "l"), kind="data"))
    d.add(Arrow((mem, "t"), (soc, "b"), heads="both"))
    d.add(Arrow((soc, "r"), (host, "l"), heads="both", label="bridge"))
    return d
