#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Radix-2 SDF FFT: log2(N) stages in a row, the delay of stage k is N/2**(k+1); inside a stage the
# butterfly works with a delay-feedback memory and a twiddle multiplier.

from pri_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 330)
    s0 = d.add(Box(70, 30, 140, 50, label="Stage 0, D=N/2", fill=COLOR_ACCENT))
    s1 = d.add(Box(260, 30, 140, 50, label="Stage 1, D=N/4", fill=COLOR_ACCENT_LIGHT))
    s2 = d.add(Box(450, 30, 140, 50, label="Last stage, D=1", fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((15, s0.cy), (s0, "l"), kind="data"))
    chain(d, [s0, s1])
    d.add(Arrow((s1, "r"), (s2, "l"), kind="data", label="...", label_pos=(425, s1.cy - 14)))
    d.add(Arrow((s2, "r"), (745, s2.cy), kind="data", label="bit-reversed", label_pos=(668, s2.cy - 14)))
    d.add(Container(70, 120, 520, 195, title="One stage", title_pos="br"))
    bf = d.add(Box(120, 170, 130, 54, label="Butterfly", fill=COLOR_ACCENT))
    dl = d.add(Box(120, 250, 130, 46, label="Delay D"))
    tw = d.add(Box(330, 170, 150, 54, label="Twiddle multiply"))
    d.add(Arrow((bf, "b", 0.3), (dl, "t", 0.3), kind="data"))
    d.add(Arrow((dl, "t", 0.7), (bf, "b", 0.7), kind="data"))
    d.add(Arrow((bf, "r"), (tw, "l"), kind="data"))
    d.add(Arrow((85, bf.cy), (bf, "l"), kind="data"))
    d.add(Arrow((tw, "r"), (570, tw.cy), kind="data"))
    return d
