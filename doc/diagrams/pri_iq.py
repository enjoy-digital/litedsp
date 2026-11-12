#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Spectrum of a real tone (two mirror lines at -f0 and +f0) and of a complex tone I + jQ (one line
# at +f0): complex baseband tells positive from negative frequencies.

from pri_helpers import *


def panel(d, x, title, lines):
    d.add(Container(x, 15, 350, 200, title=title, title_pos="tl"))
    y, x0, x1 = 160, x + 25, x + 300
    mid = (x0 + x1)/2
    axis(d, x0, x1, y, "f")
    d.add(Bus([(mid, y - 4), (mid, y + 4)]))
    d.add(Text(mid, y + 18, "0", size=13))
    for f in (-1, 1):
        d.add(Text(mid + f*110, y + 18, "+f0" if f > 0 else "-f0", size=13))
        d.add(Bus([(mid + f*110, y - 4), (mid + f*110, y + 4)]))
    for f in lines:
        tone(d, mid + f*110, y, 90)


def build():
    d = Diagram(CANVAS_WIDTH, 230)
    panel(d, 20, "Real signal", (-1, 1))
    panel(d, 390, "Complex signal I + jQ", (1,))
    return d
