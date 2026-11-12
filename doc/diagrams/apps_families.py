#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# The four application families on the shared LiteDSP base.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    fams = ["Motor control", "Audio", "Radar and sonar", "Image and video"]
    tops = []
    for k, f in enumerate(fams):
        tops.append(d.add(Box(20 + k*185, 20, 165, 50, label=f, fill=COLOR_ACCENT)))
    d.add(Container(20, 110, 720, 125, title="Shared base", title_pos="br"))
    names = ["Block contract", "Registry", "Tools, datasheets", "Golden models,\ntests"]
    base = []
    for k, n in enumerate(names):
        base.append(d.add(Box(40 + k*175, 135, 145, 50, label=n)))
    for t, b in zip(tops, base):
        d.add(Arrow((t.cx, t.y + t.h), (t.cx, 110)))
    return d
