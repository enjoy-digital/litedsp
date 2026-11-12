#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Enjoy-Digital <enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Streaming bench (bench/stream.py): DDC output as UDP I/Q packets, control over Etherbone.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 340)
    d.add(Container(20, 20, 560, 260, title="BenchSoC (SoCMini)", title_pos="tr"))
    src   = d.add(Box(45,  60,  120, 50, label="NCO tone,\nnoise, IQAdd", fill=COLOR_ACCENT_LIGHT))
    ddc   = d.add(Box(205, 60,  100, 50, label="DDC /64", fill=COLOR_ACCENT))
    udp   = d.add(Box(345, 60,  130, 50, label="UDP I/Q\nstreamer", fill=COLOR_ACCENT))
    eb    = d.add(Box(205, 170, 270, 50, label="Etherbone, UDP/IP core"))
    phy   = d.add(Box(45,  170, 120, 50, label="RGMII PHY"))
    host  = d.add(Box(620, 160, 120, 70, label="Host\nlitex_server,\nUDP socket", fill=COLOR_HARDWARE))
    d.add(Arrow((src, "r"), (ddc, "l"), kind="data"))
    d.add(Arrow((ddc, "r"), (udp, "l"), kind="accent"))
    d.add(Arrow((410, 110), (410, 170), kind="accent", label="packets", label_side="right"))
    d.add(Arrow((eb, "l"), (phy, "r"), kind="data", heads="both"))
    d.add(Arrow((phy, "b"), (host, "b"), via=[(105, 310), (680, 310)], kind="data", heads="both", label="Gigabit Ethernet", label_pos=(400, 302)))
    d.add(Arrow((255, 170), (255, 110), kind="control", label="registers", label_side="right"))
    return d
