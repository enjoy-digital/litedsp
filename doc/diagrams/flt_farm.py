#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Resampler farm: per-channel sinks scanned in round robin, one channel-major history RAM, one
# shared complex MAC with the coefficient ROM or banks, a channel-tagged output for a demux.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 250)
    ch0 = d.add(Box(10,  25,  90, 44, label="Channel 0"))
    ch1 = d.add(Box(10,  95,  90, 44, label="Channel 1"))
    chn = d.add(Box(10,  165, 90, 44, label="Last channel"))
    rr  = d.add(Box(135, 25,  100, 184, label="Round-robin\nscan"))
    his = d.add(Box(270, 89,  115, 56, label="History RAM\nby channel", fill=COLOR_ACCENT_LIGHT))
    mac = d.add(Box(420, 89,  110, 56, label="Shared\ncomplex MAC", fill=COLOR_ACCENT))
    out = d.add(Box(565, 89,  95,  56, label="Tagged\noutput"))
    dmx = d.add(Box(685, 89,  65,  56, label="Demux"))
    rom = d.add(Box(420, 180, 110, 50, label="Coefficient\nROM or banks"))
    for ch in (ch0, ch1, chn):
        d.add(Arrow((ch, "r"), (rr.x, ch.cy), kind="data"))
    d.add(Arrow((rr.x + rr.w, his.cy), (his, "l"), kind="data"))
    d.add(Arrow((his, "r"), (mac, "l"), kind="accent"))
    d.add(Arrow((mac, "r"), (out, "l"), kind="accent"))
    d.add(Arrow((out, "r"), (dmx, "l"), kind="data"))
    d.add(Arrow((rom, "t"), (mac, "b"), kind="control"))
    return d
