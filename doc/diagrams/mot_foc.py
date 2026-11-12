#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# The LiteDSPFOC composite: Clarke, Park, d/q controller, inverse Park, SVPWM; shared sin/cos.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 260)
    d.add(Container(20, 15, 600, 230, title="LiteDSPFOC", title_pos="br"))
    w = 100
    clk = d.add(Box(40,  45, 90, 56, label="Clarke", fill=COLOR_ACCENT_LIGHT))
    prk = d.add(Box(155, 45, 90, 56, label="Park", fill=COLOR_ACCENT))
    dqc = d.add(Box(270, 45, 100, 56, label="d/q\ncontroller", fill=COLOR_ACCENT))
    ipk = d.add(Box(395, 45, 90, 56, label="Inverse\nPark", fill=COLOR_ACCENT))
    svm = d.add(Box(510, 45, 90, 56, label="SVPWM", fill=COLOR_ACCENT_LIGHT))
    scs = d.add(Box(155, 140, 90, 56, label="Sin/cos"))
    dly = d.add(Box(395, 140, 90, 56, label="Delay"))
    pwm = d.add(Box(650, 45, 90, 56, label="PWM", fill=COLOR_HARDWARE))
    d.add(Arrow((clk.cx, 0), (clk, "t"), kind="data", label="currents", label_pos=(clk.cx + 38, 28)))
    for a, b in ((clk, prk), (prk, dqc), (dqc, ipk), (ipk, svm), (svm, pwm)):
        d.add(Arrow((a, "r"), (b, "l"), kind="data"))
    d.add(Arrow((0, scs.cy), (scs, "l"), kind="data", label="angle", label_pos=(70, scs.cy - 12)))
    d.add(Arrow((scs, "t"), (prk, "b")))
    d.add(Arrow((scs, "r"), (dly, "l")))
    d.add(Arrow((dly, "t"), (ipk, "b")))
    return d
