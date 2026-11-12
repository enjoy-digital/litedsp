#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# A burst receiver built from the communications blocks: acquisition (coarse CFO, derotation,
# preamble detection) then tracking (matched filter, carrier loop, timing recovery, decisions).

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 330)
    acq = d.add(Container(10, 20, 740, 120, title="Acquisition", title_pos="tr"))
    trk = d.add(Container(10, 180, 740, 130, title="Tracking", title_pos="bl"))
    w, h, y0, y1 = 130, 56, 62, 210
    cfo   = d.add(Box(40,  y0, w, h, label="CFO\nestimator", fill=COLOR_ACCENT))
    derot = d.add(Box(310, y0, w, h, label="Derotator", fill=COLOR_ACCENT_LIGHT))
    sync  = d.add(Box(580, y0, w, h, label="Frame sync", fill=COLOR_ACCENT))
    mf    = d.add(Box(580, y1, w, h, label="Matched\nfilter", fill=COLOR_ACCENT_LIGHT))
    car   = d.add(Box(400, y1, w, h, label="Carrier loop", fill=COLOR_ACCENT))
    tim   = d.add(Box(220, y1, w, h, label="Timing\nrecovery", fill=COLOR_ACCENT))
    dec   = d.add(Box(40,  y1, w, h, label="Slicer or\ndemapper", fill=COLOR_ACCENT))
    d.add(Arrow((cfo.cx, 0), (cfo, "t"), kind="data", label="I/Q in", label_pos=(cfo.cx + 8, 12),
        label_anchor="start"))
    d.add(Arrow((cfo, "r"), (derot, "l"), kind="data", label="I/Q", label_pos=(240, cfo.cy - 10)))
    d.add(Arrow((cfo.x + w/2, cfo.y + h), (derot.x + w/2, derot.y + h), kind="feedback",
        via=[(cfo.x + w/2, cfo.y + h + 14), (derot.x + w/2, derot.y + h + 14)],
        label="phase_inc", label_pos=(240, cfo.y + h + 9)))
    d.add(Arrow((derot, "r"), (sync, "l"), kind="data", label="I/Q", label_pos=(510, derot.cy - 10)))
    d.add(Arrow((sync, "b"), (mf, "t"), kind="data", label="first, last", label_pos=(sync.cx + 40, 165),
        label_anchor="start"))
    d.add(Arrow((mf, "l"), (car, "r"), kind="data"))
    d.add(Arrow((car, "l"), (tim, "r"), kind="data", label="2 sps", label_pos=(375, mf.cy - 10)))
    d.add(Arrow((tim, "l"), (dec, "r"), kind="data", label="1 sps", label_pos=(195, mf.cy - 10)))
    return d
