#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Shared helper of the communications figures (pri_modem, pri_fec_chain, pri_ofdm): a transmit
# row flowing right into a channel box, and the matching receive row flowing back left under it.
# Not a figure (no build()).

from svgdiag import *


def mirrored_chain(d, tx, rx, channel, tx_labels=(), rx_labels=(), top=50, h=56, gap=90,
    x0=20, w=118, step=150, ch_w=110, accent_rx=False):
    """Draw tx boxes left to right, rx boxes right to left under them, a channel box at the right.

    tx/rx: lists of (label, fill). tx_labels/rx_labels: arrow labels between consecutive boxes
    (len(tx)-1 / len(rx)-1 entries, None for no label). Returns (tx_boxes, rx_boxes, channel_box).
    """
    tx_y, rx_y = top, top + h + gap
    tx_boxes = [d.add(Box(x0 + i*step, tx_y, w, h, label=l, fill=f)) for i, (l, f) in enumerate(tx)]
    rx_boxes = [d.add(Box(x0 + i*step, rx_y, w, h, label=l, fill=f)) for i, (l, f) in enumerate(rx)]
    ch_x = x0 + max(len(tx), len(rx))*step
    ch   = d.add(Box(ch_x, tx_y, ch_w, rx_y + h - tx_y, label=channel, fill=COLOR_HARDWARE))
    for i, (a, b) in enumerate(zip(tx_boxes, tx_boxes[1:] + [ch])):
        label = tx_labels[i] if i < len(tx_labels) else None
        d.add(Arrow((a.x + a.w, a.cy), (b.x, a.cy), kind="data", label=label,
            label_pos=((a.x + a.w + b.x)/2, a.y - 10)))
    for i, (a, b) in enumerate(zip([ch] + rx_boxes[::-1], rx_boxes[::-1])):
        label = rx_labels[i] if i < len(rx_labels) else None
        y = rx_y + h/2
        d.add(Arrow((a.x, y), (b.x + b.w, y), kind="accent" if accent_rx else "data", label=label,
            label_pos=((a.x + b.x + b.w)/2, rx_y - 10)))
    return tx_boxes, rx_boxes, ch
