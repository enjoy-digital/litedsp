#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# valid/ready handshake: samples A, B, C; the sink stalls (ready low) while B is offered, so B is
# held until the next cycle. A beat transfers on each cycle where valid and ready are both high.

from pri_helpers import *

A, AL = COLOR_ACCENT, COLOR_ACCENT_LIGHT


def build():
    n, p, x = 7, 70, 170
    d = Diagram(CANVAS_WIDTH, 215)
    cycle_ticks(d, x, 14, 200, p, n)
    row_name(d, x, 35, "clk")
    clock(d, x, 35, p, n)
    row_name(d, x, 80, "valid")
    level(d, x, 80, p, "0111100")
    row_name(d, x, 125, "ready")
    level(d, x, 125, p, "1101111")
    row_name(d, x, 172, "data")
    data(d, x, 172, p, [None, ("A", A), ("B", AL), ("B", A), ("C", A), None, None])
    return d
