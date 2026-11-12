#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Viterbi decoder, decision-memory architecture: branch metrics feed the add-compare-select
# units, whose path metrics loop back; the decisions go to a RAM that a folded traceback reads
# from the best state.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 300)
    w, h, y0, y1 = 130, 56, 70, 200
    bm   = d.add(Box(20,  y0, w, h, label="Branch\nmetrics", fill=COLOR_ACCENT_LIGHT))
    acs  = d.add(Box(205, y0, w, h, label="ACS units", fill=COLOR_ACCENT, stack=2))
    pm   = d.add(Box(400, y0, w, h, label="Path\nmetrics", fill=COLOR_ACCENT_LIGHT))
    best = d.add(Box(600, y0, w, h, label="Best state", fill=COLOR_ACCENT_LIGHT))
    ram  = d.add(Box(205, y1, w, h, label="Decision\nRAM", fill=COLOR_ACCENT))
    tb   = d.add(Box(400, y1, w, h, label="Traceback", fill=COLOR_ACCENT))
    d.add(Arrow((bm, "r"), (acs, "l"), kind="data"))
    d.add(Arrow((acs.x + acs.w + 6, acs.cy), (pm, "l"), kind="data"))
    d.add(Arrow((pm.x + pm.w/2, pm.y), (acs.x + acs.w/2, acs.y - 6), kind="feedback",
        via=[(pm.x + pm.w/2, 35), (acs.x + acs.w/2, 35)], label="old metrics",
        label_pos=(368, 30)))
    d.add(Arrow((pm, "r"), (best, "l"), kind="control", label="minimum", label_pos=(565, pm.cy - 8)))
    d.add(Arrow((acs.x + acs.w/2, acs.y + acs.h), (ram, "t"), kind="data", label="one row",
        label_pos=(acs.x + acs.w/2 + 10, 165), label_anchor="start"))
    d.add(Arrow((ram, "r"), (tb, "l"), kind="data"))
    d.add(Arrow((best.x + best.w/2, best.y + best.h), (tb.x + tb.w, tb.y + 16), kind="control",
        via=[(best.x + best.w/2, tb.y + 16)], label="start state", label_pos=(605, tb.y + 10),
        label_anchor="start"))
    d.add(Arrow((tb.x + tb.w, tb.y + 42), (740, tb.y + 42), kind="accent", label="decoded bit",
        label_pos=(605, tb.y + 60), label_anchor="start"))
    d.add(Text(20, y0 - 12, "LLRs or bits", size=FONT_SIZE_SM, anchor="start"))
    return d
