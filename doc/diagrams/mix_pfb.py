#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# PFB channelizer: commutator, banked sample history, one shared polyphase MAC with the prototype
# ROM, M-point transform (direct DFT or radix-2 FFT), framed channel output.

from svgdiag import *


def build():
    d = Diagram(CANVAS_WIDTH, 230)
    inp = d.add(Box(10,  60, 85,  56, label="Input\nI/Q"))
    com = d.add(Box(120, 60, 110, 56, label="Commutator"))
    his = d.add(Box(255, 60, 110, 56, label="History\nM branches", stack=2))
    mac = d.add(Box(395, 60, 105, 56, label="Shared\nMAC", fill=COLOR_ACCENT))
    dft = d.add(Box(530, 60, 110, 56, label="M-point\ntransform", fill=COLOR_ACCENT))
    out = d.add(Box(665, 60, 85,  56, label="Framed\nchannels"))
    rom = d.add(Box(395, 160, 105, 50, label="Prototype\nROM", fill=COLOR_ACCENT_LIGHT))
    d.add(Arrow((inp, "r"), (com, "l"), kind="data"))
    d.add(Arrow((com, "r"), (his, "l"), kind="data"))
    d.add(Arrow((his.x + his.w + 8, his.cy), (mac, "l"), kind="accent"))
    d.add(Arrow((mac, "r"), (dft, "l"), kind="accent", label="M sums", label_pos=(515, 48)))
    d.add(Arrow((dft, "r"), (out, "l"), kind="data"))
    d.add(Arrow((rom, "t"), (mac, "b"), kind="control", label="taps", label_pos=(455, 142),
        label_anchor="start"))
    return d
