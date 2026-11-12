#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# One trellis step of the K=3 rate-1/2 convolutional code (generators 7, 5 octal): four states
# at time n, four at time n+1, two branches leaving and two entering each state. The two
# branches entering state 00 are highlighted: the add-compare-select keeps one of them.

from svgdiag import *

# Encoder K=3, G = (7, 5) octal; state = (b[n-1], b[n-2]).
def _outputs(state, bit):
    s1, s0 = (state >> 1) & 1, state & 1
    g0 = bit ^ s1 ^ s0  # 7 = 111.
    g1 = bit ^ s0       # 5 = 101.
    return f"{g0}{g1}"


def build():
    d = Diagram(CANVAS_WIDTH, 320)
    left_x, right_x, w, h = 160, 530, 70, 40
    ys = [50, 120, 190, 260]
    d.add(Text(left_x + w/2, 30, "time n", size=FONT_SIZE_SM))
    d.add(Text(right_x + w/2, 30, "time n+1", size=FONT_SIZE_SM))
    src = [d.add(Box(left_x,  y, w, h, label=f"{s:02b}", fill=COLOR_ACCENT_LIGHT if s in (0, 1) else COLOR_FILL))
           for s, y in enumerate(ys)]
    dst = [d.add(Box(right_x, y, w, h, label=f"{s:02b}", fill=COLOR_ACCENT if s == 0 else COLOR_FILL))
           for s, y in enumerate(ys)]
    # Branches: from state s with input bit b to state (b, s1). Each source leaves at two heights
    # (input 0 above, 1 below), each destination is entered at two heights (from the lower and
    # the higher numbered predecessor); every branch jogs at its own x.
    gap_x0, gap_x1 = left_x + w, right_x
    jog = 0
    for s in range(4):
        for b in (0, 1):
            t     = (b << 1) | (s >> 1)
            y0    = src[s].y + (8 if b == 0 else h - 8)
            y1    = dst[t].y + (16 if (s & 1) == 0 else h - 16)
            x_jog = gap_x0 + 40 + jog*30
            jog  += 1
            kind  = "accent" if t == 0 else ("control" if b == 0 else "feedback")
            via   = [(x_jog, y0), (x_jog, y1)] if abs(y0 - y1) > 0.5 else []
            d.add(Arrow((gap_x0, y0), (gap_x1, y1), kind=kind, via=via, label=_outputs(s, b),
                label_pos=(gap_x0 + 18, y0 - 3), label_size=FONT_SIZE_MIN + 1))
    return d
