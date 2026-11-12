#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# From phase quantities to rotor-frame quantities: Clarke then Park.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 170)
    abc    = d.add(Box(20,  40, 120, 56, label="Phases\na, b, c", fill=COLOR_HARDWARE))
    clarke = d.add(Box(200, 40, 120, 56, label="Clarke", fill=COLOR_ACCENT))
    park   = d.add(Box(420, 40, 120, 56, label="Park", fill=COLOR_ACCENT))
    dq     = d.add(Box(620, 40, 120, 56, label="Rotor frame\nd, q"))
    ang    = d.add(Box(420, 120, 120, 36, label="Rotor angle"))
    d.add(Arrow((abc, "r"), (clarke, "l"), kind="data"))
    d.add(Arrow((clarke, "r"), (park, "l"), kind="data", label="α, β"))
    d.add(Arrow((park, "r"), (dq, "l"), kind="data"))
    d.add(Arrow((ang, "t"), (park, "b")))
    return d
