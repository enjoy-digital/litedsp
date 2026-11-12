#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Radar front end: range gate, pulse compressor, MTI canceller and corner turn, with the stream
# kind between each pair.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 165)
    y, h = 55, 50
    adc  = d.add(Box(10, y, 60, h, label="ADC", fill=COLOR_HARDWARE))
    gate = d.add(Box(105, y, 105, h, label="Range gate", fill=COLOR_ACCENT_LIGHT))
    comp = d.add(Box(250, y, 110, h, label="Pulse\ncompressor", fill=COLOR_ACCENT))
    mti  = d.add(Box(400, y, 90, h, label="MTI", fill=COLOR_ACCENT_LIGHT))
    ct   = d.add(Box(530, y, 90, h, label="Corner\nturn", fill=COLOR_ACCENT))
    dop  = d.add(Box(660, y, 90, h, label="Doppler", fill=COLOR_FILL))
    d.add(Arrow((adc, "r"), (gate, "l"), kind="data"))
    for a, b in ((gate, comp), (comp, mti), (mti, ct)):
        d.add(Arrow((a, "r"), (b, "l"), kind="data"))
    d.add(Arrow((ct, "r"), (dop, "l"), kind="accent"))
    d.add(Text(80, 30, "I/Q", size=12))
    d.add(Text((gate.x + ct.x)/2 + 50, 30, "fast time: one pulse per frame", size=12))
    d.add(Text(690, 30, "slow time", size=12))
    d.add(Arrow((gate, "b"), (gate.cx, 135), kind="control"))
    d.add(Text(gate.cx, 150, "tx, cpi_start", size=12))
    return d
