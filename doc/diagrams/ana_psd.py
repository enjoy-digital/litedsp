#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Welch PSD: overlap replay, window and FFT on the top row, the PSD accumulator on the bottom row.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 330)
    d.add(Container(55, 15, 640, 300, title="LiteDSPWelchPSD", title_pos="tl"))
    d.add(Container(75, 165, 600, 130, title="LiteDSPPSD", title_pos="br"))
    hist = d.add(Box(80, 60, 150, 56, label="Overlap replay\nhistory RAM", fill=COLOR_ACCENT_LIGHT))
    win  = d.add(Box(290, 60, 130, 56, label="Window\nlength N"))
    fft  = d.add(Box(480, 60, 150, 56, label="FFT, SDF\nbit-reversed"))
    pw   = d.add(Box(95, 185, 120, 56, label="Power\nI² + Q²"))
    comb = d.add(Box(240, 185, 130, 56, label="Combine\nmode", fill=COLOR_ACCENT))
    ram  = d.add(Box(395, 185, 130, 56, label="Accumulator\nN bins", fill=COLOR_ACCENT))
    rd   = d.add(Box(550, 185, 110, 56, label="Readout\nnatural order"))
    d.add(Arrow((10, 88), (hist, "l"), kind="data", label="I/Q", label_pos=(30, 78)))
    d.add(Arrow((hist, "r"), (win, "l"), kind="data"))
    d.add(Arrow((win, "r"), (fft, "l"), kind="data"))
    d.add(Arrow((fft, "b"), (pw, "t"), via=[(555, 150), (155, 150)], kind="data"))
    d.add(Arrow((pw, "r"), (comb, "l"), kind="data"))
    d.add(Arrow((comb, "r"), (ram, "l"), kind="data"))
    d.add(Arrow((ram, "r"), (rd, "l"), kind="data"))
    d.add(Arrow((rd, "r"), (750, 213), kind="data", label="spectrum", label_pos=(722, 203)))
    return d
