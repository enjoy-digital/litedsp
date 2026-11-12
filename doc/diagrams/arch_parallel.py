#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Parallel variants: n samples per beat, lanes packed LSB-first in each field, adapters to serial.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 300)
    adc  = d.add(Box(10, 30, 130, 50, label="Converter\n4 samples/clock", fill=COLOR_HARDWARE))
    par  = d.add(Box(185, 30, 170, 50, label="Parallel DDC\nn_samples=4, /8", fill=COLOR_ACCENT))
    ser  = d.add(Box(575, 30, 175, 50, label="Serial blocks\n1 sample/beat"))
    pfir = d.add(Box(185, 105, 170, 50, label="Parallel FIR\nn_samples=4", fill=COLOR_ACCENT))
    p2s  = d.add(Box(400, 105, 150, 50, label="Parallel to serial", fill=COLOR_ACCENT_LIGHT))
    ser2 = d.add(Box(575, 105, 175, 50, label="Serial blocks\n1 sample/beat"))
    d.add(Arrow((adc, "r"), (par, "l"), kind="accent"))
    d.add(Arrow((par, "r"), (ser, "l"), kind="data", label="1 lane"))
    d.add(Arrow((adc, "b"), (pfir, "l"), via=[(75, 130)], kind="accent"))
    d.add(Arrow((pfir, "r"), (p2s, "l"), kind="accent"))
    d.add(Arrow((p2s, "r"), (ser2, "l"), kind="data"))
    d.add(Text(185, 200, "One beat of the i field", size=FONT_SIZE, anchor="start"))
    x0, w = 185, 100
    for k in range(4):
        d.add(Box(x0 + k*w, 218, w, 34, label=f"lane {3 - k}", radius=0,
            fill=COLOR_ACCENT if k == 3 else COLOR_FILL))
    d.add(Text(x0, 268, "MSB", size=FONT_SIZE_SM, anchor="start"))
    d.add(Text(x0 + 4*w, 268, "LSB, first sample", size=FONT_SIZE_SM, anchor="end"))
    return d
