#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Enjoy-Digital <enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# AN003 spectrum monitor: ingress timestamps, untagging, Welch PSD, host waterfall.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 270)
    d.add(Container(320, 10, 420, 140, title="LiteDSPWelchPSD", title_pos="tl"))
    ts    = d.add(Box(20,  50,  120, 50, label="Timestamper", fill=COLOR_ACCENT_LIGHT))
    untag = d.add(Box(170, 50,  120, 50, label="Time\nuntagger", fill=COLOR_ACCENT_LIGHT))
    win   = d.add(Box(340, 50,  110, 50, label="Window\nHann", fill=COLOR_ACCENT))
    fft   = d.add(Box(475, 50,  110, 50, label="FFT", fill=COLOR_ACCENT))
    psd   = d.add(Box(610, 50,  110, 50, label="PSD", fill=COLOR_ACCENT))
    core  = d.add(Box(20,  190, 120, 50, label="TimeCore"))
    host  = d.add(Box(590, 190, 150, 50, label="Host waterfall", fill=COLOR_HARDWARE))
    d.add(Arrow((core, "t"), (ts, "b"), kind="control", label="count", label_side="right"))
    d.add(Arrow((ts, "r"), (untag, "l"), kind="data"))
    d.add(Arrow((untag, "r"), (win, "l"), kind="data"))
    d.add(Arrow((win, "r"), (fft, "l"), kind="accent"))
    d.add(Arrow((fft, "r"), (psd, "l"), kind="accent"))
    d.add(Arrow((psd, "b"), (665, 190), kind="data", label="spectra", label_pos=(620, 172)))
    return d
