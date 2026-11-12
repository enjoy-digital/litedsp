#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Pulse compressor: two real-tap complex FIRs (Re h, Im h) in lock-step, a recombiner, and the
# frame tags delayed by P-1 beats.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    c = d.add(Container(150, 15, 470, 225, title="LiteDSPPulseCompressor", title_pos="bl"))
    src = d.add(Box(20, 60, 90, 50, label="Echo\nI/Q"))
    fre = d.add(Box(190, 35, 140, 44, label="FIR taps Re h", fill=COLOR_ACCENT))
    fim = d.add(Box(190, 95, 140, 44, label="FIR taps Im h", fill=COLOR_ACCENT))
    rec = d.add(Box(380, 55, 110, 64, label="Recombine,\nsaturate", fill=COLOR_ACCENT_LIGHT))
    tag = d.add(Box(190, 160, 300, 36, label="first / last delayed by P-1", fill=COLOR_FILL, size=13))
    out = d.add(Box(660, 62, 90, 50, label="Range\nprofile"))
    d.add(Arrow((src, "r"), (fre, "l"), kind="data", via=[(150, 85), (150, fre.cy)]))
    d.add(Arrow((150, 85), (fim, "l"), kind="data", via=[(150, fim.cy)]))
    d.add(Arrow((150, 85), (tag, "l"), kind="control", via=[(150, tag.cy)]))
    d.add(Arrow((fre, "r"), (rec, "l", 0.3), kind="data", via=[(355, fre.cy), (355, rec.y + rec.h*0.3)]))
    d.add(Arrow((fim, "r"), (rec, "l", 0.7), kind="data", via=[(355, fim.cy), (355, rec.y + rec.h*0.7)]))
    d.add(Arrow((rec, "r"), (out, "l"), kind="accent"))
    d.add(Arrow((tag, "r"), (out, "b"), kind="control", via=[(705, tag.cy)]))
    return d
