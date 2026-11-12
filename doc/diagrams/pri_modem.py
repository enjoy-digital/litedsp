#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Digital modem: the transmitter maps bits to symbols and shapes them; the receiver filters,
# recovers timing and carrier, then decides.

from pri_comm_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 300)
    d.add(Text(20, 30, "Transmitter", size=FONT_SIZE, anchor="start", italic=True))
    d.add(Text(20, 286, "Receiver", size=FONT_SIZE, anchor="start", italic=True))
    tx = [("Bits", COLOR_FILL), ("Symbol\nmapper", COLOR_ACCENT_LIGHT),
          ("Pulse\nshaper", COLOR_ACCENT_LIGHT), ("Up-convert\nand DAC", COLOR_FILL)]
    rx = [("Decisions", COLOR_ACCENT), ("Timing\nrecovery", COLOR_ACCENT),
          ("Carrier\nrecovery", COLOR_ACCENT), ("Matched\nfilter", COLOR_ACCENT)]
    mirrored_chain(d, tx, rx, "Channel", top=50, h=56, gap=110, w=106, step=150, ch_w=120,
        tx_labels=["", "symbols", "samples", "I/Q"],
        rx_labels=["I/Q", "samples", "samples", "symbols"])
    return d
