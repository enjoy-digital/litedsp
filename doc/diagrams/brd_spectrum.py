#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Enjoy-Digital <enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Spectrum bench (bench/spectrum.py): on-chip tone and noise, DDC, capture, readout over UARTBone.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 360)
    d.add(Container(20, 20, 560, 280, title="BenchSoC (SoCMini)", title_pos="tr"))
    nco   = d.add(Box(45,  50,  110, 46, label="NCO tone", fill=COLOR_ACCENT_LIGHT))
    noise = d.add(Box(45,  140, 110, 46, label="Noise\nsource", fill=COLOR_ACCENT_LIGHT))
    add   = d.add(Box(195, 95,  90,  46, label="IQAdd", fill=COLOR_ACCENT_LIGHT))
    ddc   = d.add(Box(325, 95,  90,  46, label="DDC /8", fill=COLOR_ACCENT))
    cap   = d.add(Box(455, 95,  100, 46, label="Capture", fill=COLOR_ACCENT))
    rd    = d.add(Box(455, 200, 100, 46, label="Register\nreader"))
    uart  = d.add(Box(195, 200, 120, 46, label="UARTBone"))
    host  = d.add(Box(620, 200, 120, 60, label="Host\nlitex_server", fill=COLOR_HARDWARE))
    d.add(Arrow((nco, "r"), (240, 95), via=[(240, 73)], kind="data"))
    d.add(Arrow((noise, "r"), (240, 141), via=[(240, 163)], kind="data"))
    d.add(Arrow((add, "r"), (ddc, "l"), kind="accent"))
    d.add(Arrow((ddc, "r"), (cap, "l"), kind="accent"))
    d.add(Arrow((cap, "b"), (rd, "t"), kind="data"))
    d.add(Arrow((470, 141), (345, 223), via=[(470, 170), (345, 170)], kind="data", label="memory window", label_pos=(400, 162)))
    d.add(Arrow((uart, "b"), (host, "b"), via=[(255, 330), (680, 330)], kind="control", heads="both", label="serial", label_pos=(470, 324)))
    d.add(Arrow((uart, "r"), (rd, "l"), kind="control", heads="both", label="bus", label_pos=(410, 214)))
    return d
