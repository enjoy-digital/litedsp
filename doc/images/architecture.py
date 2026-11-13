#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""architecture.svg: LiteDSP architecture, in the classic LiteX diagram style (white canvas,
chamfered boxes, grey arrows, the EnjoyDigital and "Built with LiteX" logos embedded from this
directory): converters, frontend, the block families, the LiteX SoC, the host and the tooling.

    python3 doc/images/architecture.py   # -> architecture.svg
    inkscape architecture.svg --export-type=png --export-filename=architecture.png \
        --export-width=3000

The SVG stays editable by hand (Inkscape or XML): the generator only keeps the geometry consistent.
Layout rules: arrows leave and enter boxes at their centre lines, boxes of one column share their
edges, every label has room (Carlito/Calibri metrics) between the things it sits between.
"""

import os
import base64
import argparse

FONT = "Calibri, Carlito, 'Liberation Sans', Arial, Helvetica, sans-serif"
STROKE, TEXT, ARROW, THICK = "#7f7f7f", "#1a1a1a", "#595959", "#8c8c8c"
MEM, HARD, GROUP, FPGA, BOARD = "#c9c9c9", "#dcdcdc", "#f3f3f3", "#e4e4e4", "#f8f8f8"
KEY = "#cdcdcd"   # USB3-PIPE blocks.
out   = []
boxes = []

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def box(x1, y1, x2, y2, fill="#ffffff", c=14, lines=(), shadow=True, dash=False):
    pts = f"{x1},{y1} {x2-c},{y1} {x2},{y1+c} {x2},{y2} {x1+c},{y2} {x1},{y2-c}"
    extra = ' stroke-dasharray="7,4"' if dash else ""
    filt = ' filter="url(#shadow)"' if shadow else ""
    out.append(f'  <polygon points="{pts}" fill="{fill}" stroke="{STROKE}" '
               f'stroke-width="1.5"{extra}{filt}/>')
    title = (lines[0][0] if isinstance(lines[0], tuple) else lines[0]) if lines else ""
    boxes.append((title, x1, y1, x2, y2))
    if lines:
        text_lines((x1 + x2)/2, (y1 + y2)/2, lines)

def text_lines(cx, cy, lines, anchor="middle"):
    # lines: (text, size, weight, style); weight/style optional. A vertically centred block.
    norm = []
    for l in lines:
        l = (l + (None,)*4)[:4] if isinstance(l, tuple) else (l, 13, None, None)
        norm.append((l[0], l[1] or 13, l[2], l[3]))
    heights = [s*1.3 for _, s, _, _ in norm]
    y = cy - sum(heights)/2
    for (t, s, w, st), h in zip(norm, heights):
        text(cx, y + h*0.5 + s*0.35, t, s, anchor=anchor, weight=w, style=st)
        y += h

def text(x, y, t, size=13, anchor="middle", weight=None, style=None, fill=TEXT, rotate=None):
    attrs = f'x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" fill="{fill}"'
    if weight: attrs += f' font-weight="{weight}"'
    if style:  attrs += f' font-style="{style}"'
    if rotate: attrs += f' transform="rotate({rotate} {x} {y})"'
    out.append(f'  <text {attrs}>{esc(t)}</text>')

def head(x, y, dx, dy, col, size=9):
    # A filled triangle with its tip at (x, y), pointing along (dx, dy).
    px, py = -dy, dx
    bx, by = x - dx*size, y - dy*size
    hw = size*0.42
    out.append(f'  <polygon points="{x:.1f},{y:.1f} {bx+px*hw:.1f},{by+py*hw:.1f} '
               f'{bx-px*hw:.1f},{by-py*hw:.1f}" fill="{col}"/>')

def arrow(pts, double=False, thick=False):
    col  = THICK if thick else ARROW
    wdt  = 4 if thick else 1.6
    size = 11 if thick else 9
    p = [list(q) for q in pts]
    def unit(a, b):
        dx, dy = b[0]-a[0], b[1]-a[1]
        n = (dx*dx + dy*dy) ** 0.5
        return dx/n, dy/n
    heads = []
    dx, dy = unit(p[-2], p[-1]); heads.append((p[-1][0], p[-1][1], dx, dy))
    p[-1] = [p[-1][0] - dx*(size-2), p[-1][1] - dy*(size-2)]
    if double:
        dx, dy = unit(p[1], p[0]); heads.append((p[0][0], p[0][1], dx, dy))
        p[0] = [p[0][0] - dx*(size-2), p[0][1] - dy*(size-2)]
    d = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in p)
    out.append(f'  <path d="{d}" fill="none" stroke="{col}" stroke-width="{wdt}" '
               f'stroke-linejoin="round"/>')
    for x, y, dx, dy in heads:
        head(x, y, dx, dy, col, size)

def image(path, x, y, w, h):
    data = base64.b64encode(open(path, "rb").read()).decode()
    out.append(f'  <image x="{x}" y="{y}" width="{w}" height="{h}" '
               f'xlink:href="data:image/png;base64,{data}"/>')

def line(x1, y1, x2, y2, col=STROKE, w=1):
    out.append(f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" '
               f'stroke-width="{w}"/>')

def begin(W, H, name, title, desc):
    out.clear()
    boxes.clear()
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="{name}-title {name}-description">')
    out.append(f'  <title id="{name}-title">{esc(title)}</title>')
    out.append(f'  <desc id="{name}-description">{esc(desc)}</desc>')
    out.append('  <!-- Editable SVG, classic LiteX diagram style: chamfered boxes, grey arrows, '
               'light fills. Generated by doc/images/architecture.py; edit either. -->')
    out.append('  <defs>')
    out.append(
        '    <filter id="shadow" x="-10%" y="-10%" width="125%" height="130%">'
        '<feGaussianBlur in="SourceAlpha" stdDeviation="2.4" result="b"/>'
        '<feOffset in="b" dx="3" dy="3" result="o"/>'
        '<feComponentTransfer in="o" result="s">'
        '<feFuncA type="linear" slope="0.32"/>'
        '</feComponentTransfer>'
        '<feMerge>'
        '<feMergeNode in="s"/>'
        '<feMergeNode in="SourceGraphic"/>'
        '</feMerge>'
        '</filter>')
    out.append('  </defs>')
    out.append(f'  <g id="{name}" font-family="{FONT}">')
    out.append(f'  <rect width="{W}" height="{H}" fill="#ffffff"/>')

def finish(path):
    out.append('  </g>')
    out.append('</svg>')
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(path, len("\n".join(out)))

DESC = ("LiteDSP: converters (ADC/DAC) connect through the frontend blocks to the LiteDSP block "
        "families (generation, mixing, filter, rate, level, correction, comm, analysis, "
        "stream, and "
        "the motor, radar, image and audio application families), which share LiteX "
        "stream.Endpoint "
        "streaming and CSR control. The LiteX SoC gives the host CSR access, capture and DMA "
        "through "
        "Wishbone or LiteDRAM, and Etherbone; the host runs the drivers, litedsp_cli and "
        "litex_server. "
        "The tooling (litedsp_flow, litedsp_gui, litedsp_gen, verification) builds and checks "
        "the chains.")

# Diagram ------------------------------------------------------------------------------------------
#
# Columns: converters 20..170 | FPGA 215..1335 (frontend 245..395, LiteDSP blocks 440..1010, LiteX
# SoC 1055..1305) | host 1390..1540.
# Rows: serial path centred on y=285; tooling below the FPGA (y 590..690).

FAMILIES = [
    ("generation/", "NCO · CORDIC · sources"),
    ("mixing/",     "mixer · DDC/DUC · PFB"),
    ("filter/",     "FIR · CIC · IIR · halfband"),
    ("rate/",       "decimation · interpolation"),
    ("level/",      "gain · AGC · DPD · CFR"),
    ("correction/", "DC offset · IQ · CFO"),
    ("comm/",       "modems · FEC · sync"),
    ("analysis/",   "FFT · PSD · statistics"),
    ("stream/",     "capture · DMA · CDC"),
]
APPS = [
    ("motor/", "FOC · PWM"),
    ("radar/", "pulse · CFAR"),
    ("image/", "kernels · colour"),
    ("audio/", "I2S/PDM · EQ"),
]

def draw(logos):
    begin(1560, 880, "architecture", "LiteDSP: portable RF/DSP building blocks for FPGAs", DESC)

    # FPGA boundary.
    box(215, 40, 1335, 560, fill=FPGA, c=30)
    text(240, 512, "FPGA", 24, anchor="start", weight="bold", style="italic")
    text(240, 538, "any vendor · LiteX SoC", 15, anchor="start", style="italic")

    # Converters, outside the FPGA.
    box(20, 235, 170, 335, fill=MEM, lines=[("Converters", 17, "bold"), ("ADC / DAC", 13),
        ("PDM · sigma-delta", 13)])
    arrow([(170, 285), (245, 285)], double=True, thick=True)

    # Frontend.
    box(245, 225, 395, 345, fill=KEY, lines=[("frontend/", 16, "bold"),
        ("converter interfaces", 13),
        ("I/Q packetizers", 13), ("UDP I/Q (LiteEth)", 13)])
    arrow([(395, 285), (440, 285)], double=True, thick=True)

    # LiteDSP blocks.
    box(440, 70, 1010, 490, fill=GROUP, c=18)
    text(725, 98, "LiteDSP blocks", 18, weight="bold")
    text(725, 118, "stream.Endpoint streaming + CSR control", 13, style="italic")
    xs = [(455, 625), (640, 810), (825, 995)]
    ys = [(132, 182), (194, 244), (256, 306)]
    for i, (name, sub) in enumerate(FAMILIES):
        (x1, x2), (y1, y2) = xs[i % 3], ys[i // 3]
        box(x1, y1, x2, y2, fill=KEY, lines=[(name, 15, "bold"), (sub, 12)])
    text(725, 334, "Application families", 15, weight="bold", style="italic")
    for i, (name, sub) in enumerate(APPS):
        x1 = 455 + i*138
        box(x1, 346, x1 + 126, 396, lines=[(name, 15, "bold"), (sub, 12)])
    text(725, 422, "Q1.15 fixed point · valid/ready backpressure · bypass · latency", 13)
    text(725, 444, "serial and parallel (N samples/clock) variants", 13)
    text(725, 470, "pure HDL, no vendor IP", 13, style="italic")

    # LiteX SoC.
    arrow([(1010, 285), (1055, 285)], double=True, thick=True)
    box(1055, 130, 1305, 420, fill=GROUP, c=18)
    text(1180, 156, "LiteX SoC", 18, weight="bold")
    box(1068, 172, 1292, 236, lines=[("CSR bus", 16, "bold"), ("per-block registers", 13),
        ("control · status", 13)])
    box(1068, 253, 1292, 317, lines=[("Capture · DMA", 16, "bold"), ("Wishbone · LiteDRAM", 13),
        ("replay · scope", 13)])
    box(1068, 334, 1292, 398, lines=[("Etherbone", 16, "bold"), ("UDP (LiteEth)", 13),
        ("remote register access", 13)])
    arrow([(1305, 285), (1390, 285)], double=True, thick=True)

    # Host.
    box(1390, 225, 1540, 345, lines=[("Host", 18, "bold"), ("Python drivers", 13),
        ("litedsp_cli", 13), ("litex_server", 13)])

    # Tooling.
    box(440, 590, 1305, 700, dash=True, shadow=False)
    text(460, 612, "Tooling", 16, anchor="start", weight="bold")
    tools = [
        ("litedsp_flow", "JSON netlist → chain / AXI IP"),
        ("litedsp_gui",  "node editor · live mode"),
        ("litedsp_gen",  "YAML → standalone Verilog"),
        ("Verification", "golden models · Verilator · P&R"),
    ]
    for i, (name, sub) in enumerate(tools):
        x1 = 455 + i*212
        box(x1, 624, x1 + 200, 686, lines=[(name, 15, "bold"), (sub, 12)])
    arrow([(725, 590), (725, 490)])

    # Caption and logos.
    cx = 780
    text(cx, 782, "LiteDSP: portable RF/DSP building blocks for FPGAs", 26, weight="bold",
        style="italic")
    text(cx, 811, "RF, communications, motor control, radar, image and audio blocks with one "
        "streaming and control interface", 15, style="italic")
    text(cx, 834, "NumPy golden models · Verilator co-simulation · any FPGA vendor · "
        "Migen/LiteX", 15, style="italic")
    image(os.path.join(logos, "enjoy-digital-logo.png"), 18, 750, 110, 110)
    text(1392, 812, "Built with", 19, anchor="end")
    image(os.path.join(logos, "litex-logo.png"), 1400, 762, 148, 85)

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    parser = argparse.ArgumentParser(description="LiteDSP architecture diagram.")
    parser.add_argument("--logos", default=here, help="Directory with enjoy-digital-logo.png and litex-logo.png.")
    parser.add_argument("--out",   default=here, help="Output directory.")
    args = parser.parse_args()
    draw(args.logos)
    finish(os.path.join(args.out, "architecture.svg"))

if __name__ == "__main__":
    main()
