#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# The PWM-paced loop: trigger, current sense and decoder, FOC, PWM.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 230)
    sen = d.add(Box(20,  30, 140, 56, label="Current\nsense"))
    dec = d.add(Box(20, 130, 140, 56, label="Position\ndecoder"))
    foc = d.add(Box(230, 30, 150, 156, label="LiteDSPFOC", fill=COLOR_ACCENT))
    pwm = d.add(Box(450, 30, 120, 156, label="LiteDSPPWM", fill=COLOR_ACCENT))
    inv = d.add(Box(630, 30, 110, 156, label="Inverter", fill=COLOR_HARDWARE))
    d.add(Arrow((sen, "r"), (foc.x, sen.cy), kind="data", label="currents"))
    d.add(Arrow((dec, "r"), (foc.x, dec.cy), kind="data", label="angle"))
    d.add(Arrow((foc.x + foc.w, 108), (pwm.x, 108), kind="data", label="duties"))
    d.add(Arrow((pwm.x + pwm.w, 108), (inv.x, 108), kind="data", label="gates"))
    d.add(Arrow((pwm.cx, pwm.y + pwm.h), (dec.cx, dec.y + dec.h),
        via=[(pwm.cx, 210), (dec.cx, 210)], kind="feedback", label="trigger", label_pos=(330, 200)))
    d.add(Arrow((pwm.cx, pwm.y), (sen.cx, sen.y), via=[(pwm.cx, 12), (sen.cx, 12)], kind="feedback"))
    return d
