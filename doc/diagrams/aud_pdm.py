#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# PDM receiver: bitstream interface, per-channel sinc decimators, DC blocker, compensation, TDM mux.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 170)
    mic = d.add(Box(20,  50, 90, 56, label="PDM\nmics", fill=COLOR_HARDWARE))
    itf = d.add(Box(140, 50, 105, 56, label="Bitstream\ninterface", fill=COLOR_ACCENT_LIGHT))
    dec = d.add(Box(275, 50, 105, 56, label="Sinc\ndecimator", stack=1, fill=COLOR_ACCENT))
    dcb = d.add(Box(410, 50, 90, 56, label="DC\nblocker", stack=1))
    cmp = d.add(Box(530, 50, 100, 56, label="Droop\nFIR", stack=1))
    mux = d.add(Box(660, 50, 80, 56, label="TDM\nmux", fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((itf.x, 70), (mic.x + mic.w, 70), label="mclk", label_pos=(125, 60)))
    d.add(Arrow((mic.x + mic.w, 92), (itf.x, 92), kind="data"))
    for a, b in ((itf, dec), (dec, dcb), (dcb, cmp), (cmp, mux)):
        d.add(Arrow((a, "r"), (b, "l"), kind="data"))
    d.add(Text(400, 140, "one decimator, DC blocker and FIR per channel", size=FONT_SIZE_SM))
    return d
