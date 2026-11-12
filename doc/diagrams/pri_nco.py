#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# NCO: the phase accumulator adds phase_inc on each accepted sample; the top phase bits address
# cos and sin lookup tables that give the I and Q outputs.

from pri_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    inc = d.add(Box(20, 40, 130, 50, label="phase_inc"))
    add = d.add(Box(210, 40, 90, 50, label="Add", fill=COLOR_ACCENT))
    reg = d.add(Box(210, 150, 90, 50, label="Phase", fill=COLOR_ACCENT))
    cos = d.add(Box(470, 20, 150, 50, label="Cos table", fill=COLOR_ACCENT_LIGHT))
    sin = d.add(Box(470, 100, 150, 50, label="Sin table", fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((inc, "r"), (add, "l"), kind="data"))
    d.add(Arrow((reg, "l"), (add, "l", 0.8), via=[(180, reg.cy), (180, add.y + 40)], kind="feedback"))
    d.add(Arrow((add, "b"), (reg, "t"), kind="data"))
    d.add(Arrow((add, "r"), (cos, "l"), via=[(400, add.cy), (400, cos.cy)], kind="data",
        label="top bits", label_pos=(350, add.cy - 14)))
    d.add(Arrow((400, cos.cy), (sin, "l"), via=[(400, sin.cy)], kind="data"))
    d.add(Arrow((cos, "r"), (740, cos.cy), kind="data", label="I", label_pos=(690, cos.cy - 12)))
    d.add(Arrow((sin, "r"), (740, sin.cy), kind="data", label="Q", label_pos=(690, sin.cy - 12)))
    return d
