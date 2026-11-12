#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Bit fields of three signed fixed-point formats: Q1.15 (the default sample), Q2.14 (a gain
# mantissa) and Q2.30 (the full product of two Q1.15 numbers).

from pri_helpers import *


def row(d, y, name, fields, bits):
    """fields: list of (n_bits, label, fill); bits: total width (MSB index printed above)."""
    x0, unit = 180, 520/32
    d.add(Text(x0 - 14, y + 14, name, size=15, anchor="end"))
    x = x0 + (32 - bits)*unit
    d.add(Text(x, y - 10, str(bits - 1), size=12))
    d.add(Text(x0 + 32*unit, y - 10, "0", size=12))
    for n, label, fill in fields:
        d.add(Box(x, y, n*unit, 28, label=label, radius=0, fill=fill, size=13))
        x += n*unit


def build():
    d = Diagram(CANVAS_WIDTH, 210)
    S, I, F = COLOR_ACCENT, COLOR_ACCENT_LIGHT, COLOR_FILL
    row(d, 30,  "Q1.15", [(1, "S", S), (15, "15 fraction bits", F)], 16)
    row(d, 95,  "Q2.14", [(1, "S", S), (1, "I", I), (14, "14 fraction bits", F)], 16)
    row(d, 160, "Q2.30", [(1, "S", S), (1, "I", I), (30, "30 fraction bits", F)], 32)
    return d
