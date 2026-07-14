#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Minimal WaveJSON -> SVG renderer for the shared stream timing diagrams.

Renders the subset of WaveJSON used by the ``*.json`` files in this directory (clock ``p``,
levels ``0``/``1``, data ``=`` with ``data`` labels, repeat ``.``) into LiteX-style grayscale
SVGs, without external dependencies. Regenerate with ``python3 doc/wavedrom/render.py``.
"""

import os
import json

CELL   = 40   # px per cycle.
ROW_H  = 34
WAVE_H = 22
LABELW = 90

def _wave_path(wave, y0):
    """Expand a wave string into per-cycle levels; returns list of (kind, label_index)."""
    cells, last = [], None
    for c in wave:
        if c == ".":
            cells.append(last)
        else:
            last = c
            cells.append(c)
    return cells

def render(spec):
    signals = spec["signal"]
    width   = LABELW + max(len(_wave_path(s["wave"], 0)) for s in signals if "wave" in s)*CELL + 10
    if "head" in spec:
        width = max(width, LABELW + 7*len(spec["head"]["text"]) + 10)
    height  = len(signals)*ROW_H + 30
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
           f'viewBox="0 0 {width} {height}" font-family="Arial, Helvetica, sans-serif">']
    out.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')
    if "head" in spec:
        out.append(f'<text x="{LABELW}" y="14" font-size="12" fill="#000000" '
                   f'font-weight="bold">{spec["head"]["text"]}</text>')
    y = 24
    for s in signals:
        name, wave = s.get("name", ""), s.get("wave", "")
        data       = list(s.get("data", []))
        out.append(f'<text x="{LABELW - 8}" y="{y + WAVE_H - 6}" font-size="12" '
                   f'fill="#000000" text-anchor="end">{name}</text>')
        cells = _wave_path(wave, y)
        x  = LABELW
        yl, yh = y + WAVE_H, y  # Low/high rails.
        pts = []
        for k, c in enumerate(cells):
            x0, x1 = x + k*CELL, x + (k + 1)*CELL
            prev = cells[k - 1] if k else None
            if c == "p":  # Clock: one rising edge per cell.
                out.append(f'<path d="M {x0} {yl} L {x0} {yh} L {x0 + CELL//2} {yh} '
                           f'L {x0 + CELL//2} {yl} L {x1} {yl}" stroke="#595959" '
                           f'fill="none" stroke-width="1.5"/>')
            elif c in "01":
                yy = yh if c == "1" else yl
                if prev in ("0", "1") and prev != c:
                    out.append(f'<line x1="{x0}" y1="{yh if prev == "1" else yl}" x2="{x0}" '
                               f'y2="{yy}" stroke="#595959" stroke-width="1.5"/>')
                out.append(f'<line x1="{x0}" y1="{yy}" x2="{x1}" y2="{yy}" '
                           f'stroke="#595959" stroke-width="1.5"/>')
            elif c == "=":
                new_cell = wave[k] == "=" if k < len(wave) else False
                if not new_cell:
                    continue  # Continuation cells are drawn as part of the run below.
                run = 1
                while k + run < len(wave) and wave[k + run] == ".":
                    run += 1
                label = data.pop(0) if data else None
                out.append(f'<rect x="{x0 + 2}" y="{yh}" width="{run*CELL - 4}" '
                           f'height="{WAVE_H}" fill="#eeeeee" stroke="#595959" stroke-width="1"/>')
                if label:
                    out.append(f'<text x="{x0 + run*CELL//2}" y="{yh + WAVE_H - 7}" font-size="11" '
                               f'fill="#000000" text-anchor="middle">{label}</text>')
            elif c == "x":
                out.append(f'<rect x="{x0}" y="{yh}" width="{CELL}" height="{WAVE_H}" '
                           f'fill="#f8f8f8" stroke="#9a9a9a" stroke-width="1"/>')
                out.append(f'<line x1="{x0}" y1="{yh}" x2="{x1}" y2="{yl}" '
                           f'stroke="#c0c0c0" stroke-width="1"/>')
        y += ROW_H
    out.append("</svg>")
    return "\n".join(out) + "\n"

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    for name in sorted(os.listdir(here)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(here, name), encoding="utf-8") as f:
            spec = json.load(f)
        svg = render(spec)
        out = os.path.join(here, name.replace(".json", ".svg"))
        with open(out, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"Rendered {out}")

if __name__ == "__main__":
    main()
