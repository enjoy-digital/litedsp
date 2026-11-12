#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause
#
# Shared helpers of the primer figures (no build(): not a figure).
#
# Timing rows: one horizontal lane per signal (a name on the left, one column per clock cycle on a
# common time axis). Clocks are square waves, single-bit signals are level lines, data signals are
# adjoining square cells. Spectrum sketches: a frequency axis with vertical lines for the tones.

from svgdiag import *


def row_name(d, x, y, name, size=13):
    """Signal name, right-aligned, left of a lane whose cycles start at x and are centred on y."""
    d.add(Text(x - 12, y, name, size=size, anchor="end"))


def clock(d, x, y, period, n, h=16):
    """Square wave of n periods starting at x (rising edge at the start of each cycle)."""
    hi, lo = y - h/2, y + h/2
    pts = [(x, lo)]
    for i in range(n):
        r = x + i*period
        f = r + period/2
        pts += [(r, hi), (f, hi), (f, lo), (r + period, lo)]
    clean = [pts[0]]
    for p in pts[1:]:
        if abs(p[0] - clean[-1][0]) > 0.5 or abs(p[1] - clean[-1][1]) > 0.5:
            clean.append(p)
    # Merge collinear points so that no zero-length or redundant segment remains.
    merged = [clean[0]]
    for p in clean[1:]:
        if len(merged) >= 2:
            (ax, ay), (bx, by) = merged[-2], merged[-1]
            if (abs(ax - bx) < 0.5 and abs(bx - p[0]) < 0.5) or (abs(ay - by) < 0.5 and abs(by - p[1]) < 0.5):
                merged[-1] = p
                continue
        merged.append(p)
    d.add(Bus(merged, kind="control"))


def level(d, x, y, period, bits, h=16, color=None):
    """Single-bit signal: bits is a string of '0'/'1', one character per cycle."""
    hi, lo = y - h/2, y + h/2
    ys = [hi if b == "1" else lo for b in bits]
    pts = [(x, ys[0])]
    for i in range(1, len(bits)):
        t = x + i*period
        if ys[i] != ys[i - 1]:
            pts += [(t, ys[i - 1]), (t, ys[i])]
    pts.append((x + len(bits)*period, ys[-1]))
    d.add(Bus(pts, kind="control", color=color))


def data(d, x, y, period, items, h=24, size=13):
    """Data lane: items is one entry per cycle, a label, (label, fill) or None for no data.

    Consecutive equal entries merge into one cell (a held value)."""
    i = 0
    while i < len(items):
        it = items[i]
        j = i + 1
        while j < len(items) and items[j] == it and it is not None:
            j += 1
        if it is not None:
            label, fill = (it, COLOR_FILL) if isinstance(it, str) else it
            d.add(Box(x + i*period, y - h/2, (j - i)*period, h, label=label, radius=0, fill=fill,
                size=size))
        i = j


def cycle_ticks(d, x, y0, y1, period, n):
    """Dotted vertical markers at every rising clock edge, from y0 to y1."""
    for i in range(n + 1):
        d.add(Bus([(x + i*period, y0), (x + i*period, y1)], dash="2,3", color="#c8c8c8"))


def axis(d, x0, x1, y, label=None):
    """Horizontal frequency axis with an arrowhead and an optional label at its right end."""
    d.add(Arrow((x0, y), (x1, y), kind="control"))
    if label:
        d.add(Text(x1 + 8, y, label, size=13, anchor="start"))


def tone(d, x, y, h, kind="accent"):
    """Vertical line of height h standing on the axis at (x, y): one spectral component."""
    d.add(Arrow((x, y), (x, y - h), kind=kind))


def chain(d, boxes, kind="data"):
    """Arrows between consecutive boxes of a left-to-right chain."""
    for a, b in zip(boxes, boxes[1:]):
        d.add(Arrow((a, "r"), (b, "l"), kind=kind))
