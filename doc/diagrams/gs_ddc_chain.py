#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Enjoy-Digital <enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# First chain of the getting-started chapter: examples/ddc_chain.py in the stream simulator.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 260)
    d.add(Container(150, 20, 450, 220, title="LiteDSPDDC (example)", title_pos="br"))
    nco  = d.add(Box(175, 50,  110, 46, label="NCO", fill=COLOR_ACCENT_LIGHT))
    mix  = d.add(Box(175, 140, 110, 46, label="Mixer\ndown", fill=COLOR_ACCENT))
    fir  = d.add(Box(320, 140, 110, 46, label="FIR complex\n33 taps", fill=COLOR_ACCENT))
    deci = d.add(Box(465, 140, 110, 46, label="Down-\nsampler", fill=COLOR_ACCENT))
    src  = d.add(Box(20,  140, 100, 46, label="Two tones\nNumPy", fill=COLOR_HARDWARE))
    cap  = d.add(Box(640, 140, 100, 46, label="Capture\nNumPy", fill=COLOR_HARDWARE))
    d.add(Arrow((nco, "b"), (mix, "t"), kind="data", label="LO fs/8", label_side="right"))
    d.add(Arrow((src, "r"), (mix, "l"), kind="data"))
    d.add(Arrow((mix, "r"), (fir, "l"), kind="accent"))
    d.add(Arrow((fir, "r"), (deci, "l"), kind="accent"))
    d.add(Arrow((deci, "r"), (cap, "l"), kind="data"))
    return d
