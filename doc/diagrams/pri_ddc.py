#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# DDC: the mixer multiplies the input by the conjugate of the NCO output, moving the band at the
# NCO frequency to 0 Hz, then the decimator filters and lowers the rate.

from pri_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 230)
    d.add(Container(110, 15, 540, 200, title="LiteDSPDDC", title_pos="br"))
    nco = d.add(Box(170, 130, 120, 50, label="NCO"))
    mix = d.add(Box(170, 40, 120, 50, label="Mixer", fill=COLOR_ACCENT))
    dec = d.add(Box(400, 40, 150, 50, label="Decimator", fill=COLOR_ACCENT))
    d.add(Arrow((20, mix.cy), (mix, "l"), kind="data", label="fs", label_pos=(55, mix.cy - 14)))
    d.add(Arrow((nco, "t"), (mix, "b"), kind="data"))
    d.add(Arrow((mix, "r"), (dec, "l"), kind="data", label="fs", label_pos=(345, mix.cy - 14)))
    d.add(Arrow((dec, "r"), (740, dec.cy), kind="data", label="fs/R", label_pos=(700, dec.cy - 14)))
    return d
