#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Enjoy-Digital <enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Standalone core made by litedsp_gen: AXI-Lite control, one register bank per block, AXI-Stream
# data ports of the chain.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 330)
    d.add(Container(210, 20, 340, 290, title="ddc_core", title_pos="br"))
    br    = d.add(Box(230, 50,  120, 50, label="AXILite2CSR"))
    banks = d.add(Box(420, 50,  100, 50, label="Register\nbanks", stack=2))
    chain = d.add(Box(240, 170, 280, 60, label="LiteDSPFlowChain\nlo, dly, mix, lpf, deci", fill=COLOR_ACCENT))
    axil  = d.add(Box(20,  50,  150, 50, label="s_axil_*\nAXI-Lite"))
    rx    = d.add(Box(20,  175, 150, 50, label="rx_in\nAXI-Stream"))
    bb    = d.add(Box(590, 175, 150, 50, label="bb_out\nAXI-Stream"))
    clk   = d.add(Box(20,  255, 150, 36, label="sys_clk, sys_rst"))
    d.add(Arrow((axil, "r"), (br, "l"), kind="control", heads="both"))
    d.add(Arrow((br, "r"), (banks, "l"), kind="control", heads="both", label="CSR bus"))
    d.add(Arrow((470, 100), (470, 170), kind="control", label="controls", label_side="right"))
    d.add(Arrow((rx, "r"), (chain, "l"), kind="accent"))
    d.add(Arrow((chain, "r"), (bb, "l"), kind="accent"))
    d.add(Arrow((clk, "r"), (380, 230), via=[(380, 273)], kind="control"))
    return d
