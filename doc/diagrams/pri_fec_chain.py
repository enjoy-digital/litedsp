#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Concatenated FEC chain: outer Reed-Solomon code, interleaver, inner convolutional code on the
# transmit side; the receiver undoes them in reverse order, each decoder under its encoder.

from pri_comm_helpers import *


def build():
    d = Diagram(CANVAS_WIDTH, 300)
    d.add(Text(20, 30, "Transmitter", size=FONT_SIZE, anchor="start", italic=True))
    d.add(Text(20, 286, "Receiver", size=FONT_SIZE, anchor="start", italic=True))
    tx = [("Data", COLOR_FILL), ("RS encoder", COLOR_ACCENT_LIGHT), ("Interleaver", COLOR_ACCENT_LIGHT),
          ("Conv.\nencoder", COLOR_ACCENT_LIGHT)]
    rx = [("Data", COLOR_FILL), ("RS decoder", COLOR_ACCENT), ("Deinterleaver", COLOR_ACCENT),
          ("Viterbi\ndecoder", COLOR_ACCENT)]
    mirrored_chain(d, tx, rx, "Modem\nand channel", top=50, h=56, gap=110, w=106, step=150, ch_w=120,
        tx_labels=["bytes", "codewords", "bytes", "coded bits"],
        rx_labels=["LLRs", "bytes", "codewords", "bytes"])
    return d
