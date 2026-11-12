#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Enjoy-Digital <enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# AN001 FM stereo receiver: mono path, L-R path, 38 kHz regeneration from the pilot, matrix.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 340)
    demod = d.add(Box(20,  140, 120, 50, label="FM demod", fill=COLOR_ACCENT_LIGHT))
    mono  = d.add(Box(410, 50,  140, 50, label="Low-pass /4\nmono", fill=COLOR_ACCENT_LIGHT))
    fifo  = d.add(Box(170, 145, 70,  40, label="FIFO"))
    lrmix = d.add(Box(270, 140, 110, 50, label="Mixer\nL-R", fill=COLOR_ACCENT))
    lrlp  = d.add(Box(410, 140, 140, 50, label="Low-pass /4\nL-R", fill=COLOR_ACCENT))
    regen = d.add(Box(250, 245, 150, 74, label="BPF 19 kHz\nsquare\nBPF 38 kHz", fill=COLOR_ACCENT))
    mat   = d.add(Box(590, 40,  150, 160, label="IQAdd\nmatrix\nL on I\nR on Q"))
    d.add(Arrow((demod, "t"), (mono, "l"), via=[(80, 75)], kind="data", label="MPX", label_pos=(245, 68)))
    d.add(Arrow((demod, "r"), (fifo, "l"), kind="data"))
    d.add(Arrow((fifo, "r"), (lrmix, "l"), kind="data"))
    d.add(Arrow((demod, "b"), (regen, "l"), via=[(80, 282)], kind="data", label="pilot", label_pos=(165, 275)))
    d.add(Arrow((325, 245), (lrmix, "b"), kind="accent", label="38 kHz carrier", label_side="right"))
    d.add(Arrow((lrmix, "r"), (lrlp, "l"), kind="accent"))
    d.add(Arrow((mono, "r"), (590, 75), kind="data", label="L+R"))
    d.add(Arrow((lrlp, "r"), (590, 165), kind="accent", label="L-R"))
    return d
