#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# OFDM: the transmitter places one symbol per subcarrier, an inverse FFT builds the time signal
# and a cyclic prefix is prepended; the receiver removes the prefix, runs the FFT and equalizes
# each subcarrier with one complex tap.

from pri_comm_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 300)
    d.add(Text(20, 30, "Transmitter", size=FONT_SIZE, anchor="start", italic=True))
    d.add(Text(20, 286, "Receiver", size=FONT_SIZE, anchor="start", italic=True))
    tx = [("Symbol\nmapper", COLOR_FILL), ("Inverse FFT", COLOR_ACCENT_LIGHT),
          ("Cyclic prefix\ninsert", COLOR_ACCENT_LIGHT), ("DAC", COLOR_FILL)]
    rx = [("Soft\ndemapper", COLOR_FILL), ("Equalizer", COLOR_ACCENT),
          ("FFT", COLOR_ACCENT), ("Cyclic prefix\nremove", COLOR_ACCENT)]
    mirrored_chain(d, tx, rx, "Multipath\nchannel", top=50, h=56, gap=110, w=106, step=150, ch_w=120,
        tx_labels=["N bins", "N samples", "CP + N", "I/Q"],
        rx_labels=["I/Q", "N samples", "N bins", "N bins"])
    return d
