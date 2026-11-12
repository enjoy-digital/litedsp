#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# FFT family: the three engines and their options, the timing-oriented options tinted.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 300)
    d.add(Container(10, 15, 240, 270, title="SDF, streaming", title_pos="br"))
    d.add(Container(260, 15, 240, 270, title="Iterative, burst", title_pos="br"))
    d.add(Container(510, 15, 240, 270, title="Parallel, P lanes", title_pos="br"))
    # SDF: LiteDSPFFT and LiteDSPInterleavedFFT.
    d.add(Box(30, 35, 200, 56, label="Classic\n1 sample per clock", fill=COLOR_ACCENT_LIGHT))
    d.add(Box(30, 105, 200, 56, label="Folded\n1 sample per 2 clocks", fill=COLOR_ACCENT))
    d.add(Box(30, 175, 200, 56, label="Interleaved x2\ntwo folded contexts", fill=COLOR_ACCENT))
    # Iterative: LiteDSPFFTIter.
    d.add(Box(280, 35, 200, 56, label="Three-clock butterfly\nin-place BRAM", fill=COLOR_ACCENT_LIGHT))
    d.add(Box(280, 105, 200, 56, label="Registered butterfly\nfour clocks", fill=COLOR_ACCENT))
    # Parallel: LiteDSPParallelFFT.
    d.add(Box(530, 35, 200, 56, label="Split P=2\ntwo N/2 SDF cores", fill=COLOR_ACCENT_LIGHT))
    d.add(Box(530, 105, 200, 56, label="Native P=2, P=4\nvector SDF", fill=COLOR_ACCENT_LIGHT))
    d.add(Box(530, 175, 200, 56, label="Native, pipelined\nfeedback", fill=COLOR_ACCENT))
    return d
