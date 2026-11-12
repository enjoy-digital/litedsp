#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Reed-Solomon decoder: the received block is stored while the syndromes accumulate; the
# Berlekamp-Massey and Omega steps find the error locator and evaluator; the Chien scan and
# Forney formula correct the stored bytes, which then drain as the message.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 290)
    w, h, y0, y1 = 140, 56, 50, 200
    syn  = d.add(Box(20,  y0, w, h, label="Syndromes", fill=COLOR_ACCENT))
    bmk  = d.add(Box(210, y0, w, h, label="Berlekamp-\nMassey", fill=COLOR_ACCENT))
    om   = d.add(Box(400, y0, w, h, label="Omega", fill=COLOR_ACCENT_LIGHT))
    ch   = d.add(Box(590, y0, w, h, label="Chien and\nForney", fill=COLOR_ACCENT))
    ram  = d.add(Box(210, y1, 330, h, label="Codeword RAM", fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((syn, "r"), (bmk, "l"), kind="control", label="2t values", label_pos=(185, y0 - 10)))
    d.add(Arrow((bmk, "r"), (om, "l"), kind="control", label="locator", label_pos=(375, y0 - 10)))
    d.add(Arrow((om, "r"), (ch, "l"), kind="control", label="evaluator", label_pos=(565, y0 - 10)))
    d.add(Arrow((20, ram.y + 20), (ram.x, ram.y + 20), kind="data", label="n bytes in",
        label_pos=(60, ram.y + 42)))
    d.add(Arrow((syn.x + 70, ram.y + 20), (syn.x + 70, syn.y + syn.h), kind="data"))
    d.add(Arrow((ch.x + 70, ch.y + ch.h), (ram.x + ram.w, ram.y + 20), kind="control",
        via=[(ch.x + 70, ram.y + 20)], label="fix bytes", label_pos=(ch.x + 78, 160),
        label_anchor="start"))
    d.add(Arrow((ram.x + ram.w, ram.y + 42), (740, ram.y + 42), kind="accent", label="k bytes out",
        label_pos=(600, ram.y + 62), label_anchor="start"))
    return d
