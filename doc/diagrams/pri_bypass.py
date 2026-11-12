#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Delay-matched bypass of a block of latency 1: the bypass select is sampled with each beat, so the
# beats accepted while bypass is high come out unprocessed, at the same latency as processed ones.

from pri_helpers import *

A, AL = COLOR_ACCENT, COLOR_ACCENT_LIGHT


def build():
    n, p, x = 7, 70, 170
    d = Diagram(CANVAS_WIDTH, 215)
    cycle_ticks(d, x, 14, 200, p, n)
    row_name(d, x, 35, "clk")
    clock(d, x, 35, p, n)
    row_name(d, x, 80, "bypass")
    level(d, x, 80, p, "0001111")
    row_name(d, x, 127, "sink.data")
    data(d, x, 127, p, [None, "x0", "x1", "x2", "x3", "x4", None])
    row_name(d, x, 175, "source.data")
    data(d, x, 175, p, [None, None, ("f(x0)", A), ("f(x1)", A), ("x2", AL), ("x3", AL), ("x4", AL)])
    return d
