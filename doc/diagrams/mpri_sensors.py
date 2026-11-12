#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Rotor angle sources and the angle tracker.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 290)
    srcs = [("Encoder A/B", "Quadrature\ndecoder"), ("Hall sensors", "Hall\ndecoder"),
            ("Resolver", "Resolver to\ndigital"), ("Currents,\nvoltages", "Sliding-mode\nobserver")]
    decs = []
    for k, (s, dec) in enumerate(srcs):
        y = 15 + k*68
        sb = d.add(Box(20, y, 130, 56, label=s, fill=COLOR_HARDWARE))
        db = d.add(Box(200, y, 140, 56, label=dec, fill=COLOR_ACCENT_LIGHT))
        d.add(Arrow((sb, "r"), (db, "l"), kind="data"))
        decs.append(db)
    trk = d.add(Box(420, 15, 140, 260, label="Angle\ntracker", fill=COLOR_ACCENT))
    out = d.add(Box(620, 117, 120, 56, label="Angle,\nspeed"))
    for db in decs:
        d.add(Arrow((db, "r"), (trk.x, db.cy), kind="data"))
    d.add(Arrow((trk.x + trk.w, out.cy), (out, "l"), kind="data"))
    return d
