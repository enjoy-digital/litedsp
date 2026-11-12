#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# DDC composite: the input mixed down by the NCO, then decimated by a CIC or a FIR decimator.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 270)
    d.add(Container(150, 15, 420, 245, title="LiteDSPDDC", title_pos="br"))
    inp = d.add(Box(10,  60,  105, 50, label="Input I/Q\nhigh rate"))
    mix = d.add(Box(185, 55,  120, 60, label="Mixer\ndown", fill=COLOR_ACCENT))
    nco = d.add(Box(185, 160, 120, 50, label="NCO", fill=COLOR_ACCENT_LIGHT))
    dec = d.add(Box(375, 55,  160, 60, label="Decimator\nCIC or FIR", fill=COLOR_ACCENT))
    out = d.add(Box(615, 60,  130, 50, label="Baseband I/Q\nlow rate"))
    reg = d.add(Box(10,  160, 105, 50, label="phase_inc\nregister"))
    d.add(Arrow((inp, "r"), (mix, "l"), kind="accent", label="a", label_pos=(132, 77)))
    d.add(Arrow((nco, "t"), (mix, "b"), kind="data", label="LO, b", label_pos=(253, 140),
        label_anchor="start"))
    d.add(Arrow((mix, "r"), (dec, "l"), kind="accent"))
    d.add(Arrow((dec, "r"), (out, "l"), kind="accent"))
    d.add(Arrow((reg, "r"), (nco, "l"), kind="control"))
    return d
