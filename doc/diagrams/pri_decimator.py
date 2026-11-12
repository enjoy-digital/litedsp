#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Decimation by 4 (LiteDSPCICDecimator, decimation=4, in a Migen run): the sink accepts a sample on
# every cycle and the source emits one sample per four accepted inputs.

from pri_helpers import *

A, AL = COLOR_ACCENT, COLOR_ACCENT_LIGHT


def build():
    n, p, x = 10, 56, 170
    d = Diagram(CANVAS_WIDTH, 260)
    cycle_ticks(d, x, 14, 245, p, n)
    row_name(d, x, 35, "clk")
    clock(d, x, 35, p, n)
    row_name(d, x, 80, "sink.valid")
    level(d, x, 80, p, "1111111111")
    row_name(d, x, 127, "sink.data")
    data(d, x, 127, p, [f"x{k}" for k in range(n)])
    row_name(d, x, 175, "source.valid")
    level(d, x, 175, p, "0000100010")
    row_name(d, x, 222, "source.data")
    data(d, x, 222, p, [None]*4 + [("y0", A)] + [None]*3 + [("y1", A), None])
    return d
