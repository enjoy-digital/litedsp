#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# A channel-tagged TDM stream: beats of samples with their channel tags.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 140)
    d.add(Text(80, 45, "data", anchor="end"))
    d.add(Text(80, 85, "channel", anchor="end"))
    labels = ["L0", "R0", "L1", "R1", "L2", "R2"]
    for k, lab in enumerate(labels):
        x = 100 + k*105
        fill = COLOR_ACCENT if lab[0] == "L" else COLOR_ACCENT_LIGHT
        d.add(Box(x, 30, 105, 30, label=lab, radius=0, fill=fill))
        d.add(Box(x, 70, 105, 30, label=str(k % 2), radius=0))
    for f in range(3):
        d.add(Text(100 + f*210 + 105, 120, f"frame {f}", size=FONT_SIZE_SM))
    return d
