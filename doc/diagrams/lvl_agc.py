#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# AGC: gain datapath on the top row, magnitude and gain loop on the bottom row.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 330)
    d.add(Container(130, 15, 530, 110, title="datapath, one sample per clock", title_pos="tl"))
    d.add(Container(10, 160, 670, 120, title="gain loop, on accepted samples", title_pos="br"))
    mul   = d.add(Box(150, 50, 140, 56, label="Multiply\nby gain", fill=COLOR_ACCENT))
    rnd   = d.add(Box(320, 50, 140, 56, label="Round,\nsaturate"))
    oreg  = d.add(Box(490, 50, 140, 56, label="Output\nregister"))
    gain  = d.add(Box(30, 180, 140, 56, label="Gain register\nclamp", fill=COLOR_ACCENT))
    err   = d.add(Box(195, 180, 140, 56, label="Error\n(target - |y|) >> mu"))
    queue = d.add(Box(360, 180, 140, 56, label="Observation\ndelay 0, 1, 2", fill=COLOR_ACCENT_LIGHT))
    mag   = d.add(Box(525, 180, 140, 56, label="Magnitude\nmax + min/4"))
    d.add(Arrow((15, 78), (mul, "l"), kind="data", label="sink", label_side="above"))
    d.add(Arrow((mul, "r"), (rnd, "l"), kind="data"))
    d.add(Arrow((rnd, "r"), (oreg, "l"), kind="data"))
    d.add(Arrow((oreg, "r"), (745, 78), kind="data", label="source", label_side="above"))
    d.add(Arrow((700, 78), (700, 208), via=[], kind="control", heads="none"))
    d.add(Arrow((700, 208), (mag, "r"), kind="control"))
    d.add(Arrow((mag, "l"), (queue, "r"), kind="control"))
    d.add(Arrow((queue, "l"), (err, "r"), kind="control"))
    d.add(Arrow((err, "l"), (gain, "r"), kind="control"))
    d.add(Arrow((gain, "t"), (mul, "b", 0.3), via=[(100, 140), (192, 140)], kind="feedback",
        label="gain", label_pos=(75, 150)))
    d.add(Arrow((265, 315), (err, "b"), kind="control", label="target", label_pos=(305, 300)))
    d.add(Arrow((gain, "b"), (100, 315), kind="control", label="railed", label_pos=(140, 300)))
    return d
