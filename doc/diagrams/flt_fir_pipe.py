#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Real FIR datapath: sample shift register, optional symmetric fold, registered products, adder
# tree (combinational or one register per level), round and saturate, output.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 220)
    inp = d.add(Box(10,  60, 80,  56, label="Input\nsample"))
    shr = d.add(Box(110, 60, 95,  56, label="Shift\nregister"))
    fld = d.add(Box(225, 60, 85,  56, label="Fold\noptional", fill=COLOR_ACCENT_LIGHT))
    prd = d.add(Box(330, 60, 100, 56, label="Products\nregistered", fill=COLOR_ACCENT, stack=2))
    tre = d.add(Box(455, 60, 95,  56, label="Adder\ntree", fill=COLOR_ACCENT))
    rsc = d.add(Box(570, 60, 90,  56, label="Round,\nsaturate"))
    out = d.add(Box(680, 60, 70,  56, label="Output"))
    cof = d.add(Box(330, 155, 100, 50, label="Coefficient\nregisters"))
    d.add(Arrow((inp, "r"), (shr, "l"), kind="data"))
    d.add(Arrow((shr, "r"), (fld, "l"), kind="data"))
    d.add(Arrow((fld, "r"), (prd, "l"), kind="data"))
    d.add(Arrow((prd.x + prd.w + 8, prd.cy), (tre, "l"), kind="accent"))
    d.add(Arrow((tre, "r"), (rsc, "l"), kind="accent"))
    d.add(Arrow((rsc, "r"), (out, "l"), kind="data"))
    d.add(Arrow((cof, "t"), (prd, "b"), kind="control"))
    return d
