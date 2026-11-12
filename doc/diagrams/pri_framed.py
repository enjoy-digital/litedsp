#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Framed stream: first marks the first beat and last the last beat of a 4-sample frame.

from pri_helpers import *

A, AL = COLOR_ACCENT, COLOR_ACCENT_LIGHT


def build():
    n, p, x = 7, 70, 170
    d = Diagram(CANVAS_WIDTH, 260)
    cycle_ticks(d, x, 14, 245, p, n)
    row_name(d, x, 35, "clk")
    clock(d, x, 35, p, n)
    row_name(d, x, 80, "valid")
    level(d, x, 80, p, "0111100")
    row_name(d, x, 127, "data")
    data(d, x, 127, p, [None, ("s0", A), ("s1", AL), ("s2", AL), ("s3", A), None, None])
    row_name(d, x, 175, "first")
    level(d, x, 175, p, "0100000")
    row_name(d, x, 220, "last")
    level(d, x, 220, p, "0000100")
    return d
