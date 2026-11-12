#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Interpolation by 4 (LiteDSPUpsampler and LiteDSPCICInterpolator, factor 4, in a Migen run): the
# sink accepts one sample every four cycles and the source emits a sample on every cycle.

from pri_helpers import *

A, AL = COLOR_ACCENT, COLOR_ACCENT_LIGHT


def build():
    n, p, x = 10, 56, 170
    d = Diagram(CANVAS_WIDTH, 260)
    cycle_ticks(d, x, 14, 245, p, n)
    row_name(d, x, 35, "clk")
    clock(d, x, 35, p, n)
    row_name(d, x, 80, "sink.ready")
    level(d, x, 80, p, "1000100010")
    row_name(d, x, 127, "sink.data")
    data(d, x, 127, p, [("x0", A)] + [("x1", AL)]*3 + [("x1", A)] + [("x2", AL)]*3 + [("x2", A), ("x3", AL)])
    row_name(d, x, 175, "source.valid")
    level(d, x, 175, p, "0111111111")
    row_name(d, x, 222, "source.data")
    data(d, x, 222, p, [None] + [(f"y{k}", A) for k in range(n - 1)])
    return d
