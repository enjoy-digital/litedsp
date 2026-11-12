#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Enjoy-Digital <enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Flow tooling: netlist sources, the headless chain builder and IP core, and their outputs.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 420)
    gui   = d.add(Box(20,  40,  150, 50, label="Flow editor\nlitedsp_gui"))
    nl    = d.add(Box(20,  150, 150, 50, label="Netlist JSON"))
    yml   = d.add(Box(20,  260, 150, 50, label="YAML config"))
    chain = d.add(Box(300, 150, 160, 50, label="LiteDSPFlowChain", fill=COLOR_ACCENT))
    ip    = d.add(Box(300, 260, 160, 50, label="LiteDSPFlowIPCore", fill=COLOR_ACCENT_LIGHT))
    cv    = d.add(Box(585, 150, 155, 50, label="Chain Verilog"))
    core  = d.add(Box(585, 260, 155, 50, label="Core Verilog,\nregister map"))
    viv   = d.add(Box(585, 350, 155, 50, label="Vivado IP\npackage"))
    d.add(Arrow((gui, "b"), (nl, "t"), kind="data", heads="both", label="load, save", label_side="right"))
    d.add(Arrow((nl, "r"), (chain, "l"), kind="data", label="litedsp_flow"))
    d.add(Arrow((nl, "b"), (yml, "t"), kind="control", label="netlist:", label_side="right"))
    d.add(Arrow((yml, "r"), (ip, "l"), kind="data", label="litedsp_gen"))
    d.add(Arrow((chain, "b"), (ip, "t"), kind="control", label="with_csr", label_side="right"))
    d.add(Arrow((chain, "r"), (cv, "l"), kind="accent"))
    d.add(Arrow((ip, "r"), (core, "l"), kind="accent"))
    d.add(Arrow((core, "b"), (viv, "t"), kind="control", label="--vivado-ip", label_side="right"))
    return d
