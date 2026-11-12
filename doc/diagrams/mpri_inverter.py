#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Three-phase inverter: PWM gate signals, three half-bridges, current sensors, motor.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 275)
    pwm  = d.add(Box(20, 40, 110, 176, label="PWM\ngenerator", fill=COLOR_ACCENT))
    d.add(Container(200, 15, 230, 250, title="Inverter", title_pos="br"))
    bus  = d.add(Box(212, 40, 40, 176, label="DC\nbus", fill=COLOR_HARDWARE))
    legs = [d.add(Box(262, 40 + k*65, 150, 46, label=f"Half-bridge {p}", fill=COLOR_ACCENT_LIGHT))
            for k, p in enumerate("abc")]
    sens = d.add(Box(450, 40, 120, 176, label="Current\nsensors"))
    mot  = d.add(Box(610, 40, 130, 176, label="PMSM", fill=COLOR_HARDWARE))
    for l in legs:
        d.add(Arrow((pwm.x + pwm.w, l.cy - 14), (bus.x, l.cy - 14), label="2 gates",
            label_pos=((pwm.x + pwm.w + bus.x)/2, l.cy - 26)))
        d.add(Arrow((bus.x + bus.w, l.cy), (l, "l")))
        d.add(Arrow((l, "r"), (sens.x, l.cy), kind="data"))
        d.add(Arrow((sens.x + sens.w, l.cy), (mot.x, l.cy), kind="data"))
    return d
