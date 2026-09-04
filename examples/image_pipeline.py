#!/usr/bin/env python3
#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""AN012 - Image pipeline: Bayer sensor to YCbCr, statistics and an edge map.

A 32 x 24 RGB scene (colour bars over a ramp with a bright triangle) goes through a sensor model
(white-balance imbalance, 8-bit RGGB mosaic) and the RTL chain

  Debayer -> PixelGain (WB) -> ColorMatrix (RGB -> YCbCr, JPEG) -> Split
      A: PixelHistogram (Y, 256 bins)
      B: ColorMatrix (select Y) -> Kernel2D (Gaussian 3x3) -> Sobel (L1,
      /4) -> Threshold (hysteresis 96 / 64)
         -> PixelHistogram (2 bins: edge / non-edge)

twice: one free-flowing pass and one under random backpressure. Gates: the YCbCr frame is
bit-exact against the integer models and within 40 dB PSNR of the float reference; the edge map is
bit-exact against the models and agrees with a float Sobel reference on >= 95 % of the pixels;
both histograms sum to the pixel count and match np.bincount; branch B's measured latency equals
the summed declared latencies; the second frame equals the first (flush / re-sync).

Run: ``python3 examples/image_pipeline.py [--plot-dir DIR]``; prints PASS.
"""

import os
import sys
import math
import argparse

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from migen import *

from litex.gen import *

from litedsp.common          import pixel_layout
from litedsp.stream.split    import LiteDSPSplit
from litedsp.image.debayer   import LiteDSPDebayer
from litedsp.image.point     import LiteDSPPixelGain, LiteDSPThreshold
from litedsp.image.color     import LiteDSPColorMatrix
from litedsp.image.kernel    import LiteDSPKernel2D
from litedsp.image.edge      import LiteDSPSobel
from litedsp.image.histogram import LiteDSPPixelHistogram
from litedsp.image.design    import mosaic, color_preset, kernel_preset

from test.common import raster_beats
from test.models import (debayer_model, pixel_gain_model, color_matrix_model, kernel2d_model,
                         sobel_model,
                         threshold_model, histogram_model)

W, H = 32, 24
WB_R, WB_B = 0.6, 0.8                                                  # Sensor white-balance error.

# Scene --------------------------------------------------------------------------------------------

def scene():
    img = np.zeros((H, W, 3), np.int64)
    bars = [(230, 230, 230), (230, 230, 40), (40, 230, 230), (40, 230, 40), (230, 40, 230),
            (230, 40, 40), (40, 40, 230), (30, 30, 30)]
    for y in range(H):
        for x in range(W):
            if y < H//2:
                img[y, x] = bars[min(7, x//4)]
            else:
                img[y, x] = (4*x + 60, 120, 255 - 4*x)
            if y > 8 and abs(x - 20) < (y - 8)//2 and y < 20:
                img[y, x] = (250, 245, 200)
    return img

def sensor(rgb, seed=1):
    """White-balance imbalance then an RGGB mosaic."""
    rng = np.random.default_rng(seed)
    raw = rgb.astype(float)*np.array([WB_R, 1.0, WB_B]) + rng.normal(0, 1.5, rgb.shape)
    return mosaic(np.clip(np.round(raw), 0, 255).astype(np.int64), "rggb")

# Chain --------------------------------------------------------------------------------------------

class Pipeline(LiteXModule):
    def __init__(self):
        gains = [int(round(g*256)) for g in (1/WB_R, 1.0, 1/WB_B)]
        c, i, o = color_preset("rgb_to_ycbcr_jpeg")
        cy, iy, oy = color_preset("select_r")
        g3, s3, o3 = kernel_preset("gaussian3")
        self.demosaic = LiteDSPDebayer(pattern="rggb", width=W, with_csr=False)
        self.wb       = LiteDSPPixelGain(with_csr=False)
        for k in range(3):
            self.wb.gain[k].reset = gains[k]
        self.csc      = LiteDSPColorMatrix(coefficients=c, in_offsets=i, out_offsets=o,
                                           with_csr=False)
        self.split    = LiteDSPSplit(2, layout=pixel_layout(8, 3))
        self.hist_y   = LiteDSPPixelHistogram(n_channels=3, channel=0, bins_log2=8, with_csr=False)
        self.sel_y    = LiteDSPColorMatrix(n_out=1, coefficients=cy, in_offsets=iy, out_offsets=oy,
                                           with_csr=False)
        self.blur     = LiteDSPKernel2D(coefficients=g3, shift=s3, offset=o3, width=W,
                                        with_csr=False)
        self.sobel    = LiteDSPSobel(width=W, mode="l1", shift=2, with_csr=False)
        self.thresh   = LiteDSPThreshold(high=96, low=64, with_csr=False)
        self.hist_e   = LiteDSPPixelHistogram(n_channels=1, bins_log2=1, with_csr=False)
        self.gains = gains
        self.sink = self.demosaic.sink
        self.comb += [
            self.demosaic.source.connect(self.wb.sink), self.wb.source.connect(self.csc.sink),
            self.csc.source.connect(self.split.sink),
            self.split.sources[0].connect(self.hist_y.sink),
            self.split.sources[1].connect(self.sel_y.sink),
            self.sel_y.source.connect(self.blur.sink),
            self.blur.source.connect(self.sobel.sink), self.sobel.source.connect(self.thresh.sink),
            self.thresh.source.connect(self.hist_e.sink),
        ]
        self.branch_b_latency = (self.sel_y.latency + self.blur.latency + self.sobel.latency +
                                 self.thresh.latency)

def simulate(top, beats, throttle=0.0, ready_rate=1.0, seed=2, max_cycles=40000):
    """Drive the raw frames, capture the YCbCr tap, the edge map and both histograms."""
    rng = np.random.default_rng(seed)
    ycbcr, edges, hist_y, hist_e = [], [], [], []
    timing = {}
    def tap(ep, fields, store):
        @passive
        def gen():
            cyc = 0
            while True:
                if (yield ep.valid) and (yield ep.ready):
                    beat = {}
                    for f in fields:
                        beat[f] = (yield getattr(ep, f))
                    beat["cycle"] = cyc
                    store.append(beat)
                cyc += 1
                yield
        return gen()
    def sinkdrv(ep, store):
        @passive
        def gen():
            while True:
                yield ep.ready.eq(int(rng.random() < ready_rate))
                yield
                if (yield ep.valid) and (yield ep.ready):
                    store.append({"data": (yield ep.data), "first": (yield ep.first),
                                  "last": (yield ep.last)})
        return gen()
    def driver():
        cyc = 0
        for b in beats:
            while rng.random() > 1.0 - throttle:
                yield
                cyc += 1
            for f in ("data", "eol", "first", "last"):
                yield getattr(top.sink, f).eq(int(b[f]))
            yield top.sink.valid.eq(1)
            yield
            cyc += 1
            while not (yield top.sink.ready):
                yield
                cyc += 1
            yield top.sink.valid.eq(0)
        for _ in range(max_cycles):
            if len(hist_y) >= 2*256 and len(hist_e) >= 2*2:
                return
            yield
        raise RuntimeError("simulation did not complete")
    run_simulation(top, [driver(), tap(top.csc.source, ["r", "g", "b", "first"], ycbcr),
                         tap(top.thresh.source, ["data", "first"], edges),
                         tap(top.sel_y.sink, ["first"], timing.setdefault("b_in", [])),
                         sinkdrv(top.hist_y.source, hist_y), sinkdrv(top.hist_e.source, hist_e)])
    return ycbcr, edges, hist_y, hist_e, timing

# Reference ----------------------------------------------------------------------------------------

def reference(raw, top):
    """Integer model chain (bit-exact) and float references."""
    c, i, o = color_preset("rgb_to_ycbcr_jpeg")
    g3, s3, o3 = kernel_preset("gaussian3")
    rgb  = debayer_model(raw, "rggb", "mirror")
    wb, _ = pixel_gain_model(rgb, top.gains, (0, 0, 0))
    ycc, _ = color_matrix_model(wb, c, i, o)
    y = ycc[:, :, 0]
    blur, _ = kernel2d_model(y, g3, s3, o3)
    mag  = sobel_model(blur, "l1", 2)
    edge = threshold_model(mag, 96, 64)
    # Float references: matrix in float on the same white-balanced pixels; float Sobel on the
    # float-blurred Y, plain threshold at the mid level.
    m = np.array(c, float).reshape(3, 3)/4096
    ycc_f = np.clip(wb.astype(float) @ m.T + np.array(o, float), 0, 255)
    yf = y.astype(float)
    bf = (np.pad(yf, 1, mode="edge"))
    blur_f = sum(g3[k]*bf[k//3:k//3 + H, k % 3:k % 3 + W] for k in range(9))/16
    pf = np.pad(blur_f, 1, mode="edge")
    gx = (pf[0:H, 2:] - pf[0:H, :W]) + 2*(pf[1:H + 1, 2:] - pf[1:H + 1, :W]) + (pf[2:, 2:]
        - pf[2:, :W])
    gy = (pf[2:, 0:W] - pf[0:H, 0:W]) + 2*(pf[2:, 1:W + 1] - pf[0:H, 1:W + 1]) + (pf[2:, 2:]
        - pf[0:H, 2:])
    edge_f = np.where((np.abs(gx) + np.abs(gy))/4 >= 80, 255, 0)
    return dict(rgb=rgb, ycc=ycc, y=y, edge=edge, ycc_f=ycc_f, edge_f=edge_f)

def to_image(beats, fields):
    arr = np.array([[b[f] for f in fields] for b in beats[:W*H]], np.int64)
    return arr.reshape(H, W, len(fields)) if len(fields) > 1 else arr.reshape(H, W)

def check(name, ycbcr, edges, hist_y, hist_e, timing, ref, top):
    ok = True
    ycc = [to_image(ycbcr[k*W*H:], ["r", "g", "b"]) for k in range(2)]
    edg = [to_image(edges[k*W*H:], ["data"]) for k in range(2)]
    ok &= np.array_equal(ycc[0], ref["ycc"]) and np.array_equal(edg[0], ref["edge"])
    ok &= np.array_equal(ycc[1], ycc[0]) and np.array_equal(edg[1], edg[0])
    mse  = float(np.mean((ycc[0].astype(float) - ref["ycc_f"])**2))
    psnr = 10*math.log10(255**2/max(mse, 1e-9))
    agree = float(np.mean(edg[0] == ref["edge_f"]))
    hy = [np.array([b["data"] for b in hist_y[k*256:(k + 1)*256]]) for k in range(2)]
    he = [np.array([b["data"] for b in hist_e[k*2:(k + 1)*2]]) for k in range(2)]
    ok &= all(int(h.sum()) == W*H for h in hy + he)
    ok &= np.array_equal(hy[0], histogram_model(ref["ycc"], 0, 8)) and np.array_equal(he[0],
        histogram_model(ref["edge"], 0, 1))
    ok &= np.array_equal(hy[1], hy[0]) and np.array_equal(he[1], he[0])
    first_in  = next(b["cycle"] for b in timing["b_in"] if b["first"])
    first_out = next(b["cycle"] for b in edges if b["first"])
    lat = first_out - first_in
    ok &= psnr >= 40.0 and agree >= 0.95
    ok &= 0.02*W*H <= int(he[0][1]) <= 0.5*W*H                          # A real edge map.
    if name == "free-flow":
        ok &= lat == top.branch_b_latency
    print(f"[{name}] YCbCr bit-exact {np.array_equal(ycc[0], ref['ycc'])}, PSNR {psnr:.1f} dB vs "
          f"float; edge map bit-exact "
          f"{np.array_equal(edg[0], ref['edge'])}, {100*agree:.1f} % agreement with the float "
          f"Sobel; histograms {int(hy[0].sum())} / "
          f"{int(he[0].sum())} px (edge pixels {int(he[0][1])}); branch-B latency {lat} (declared "
          f"{top.branch_b_latency}); "
          f"frame 2 == frame 1 {np.array_equal(ycc[1], ycc[0]) and np.array_equal(edg[1], edg[0])}")
    return ok, dict(ycc=ycc[0], edge=edg[0], hist=hy[0])

# Plots --------------------------------------------------------------------------------------------

def plot(plot_dir, raw, ref, res):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[plot] matplotlib not installed, skipping the figure")
        return
    os.makedirs(plot_dir, exist_ok=True)
    fig, ax = plt.subplots(2, 3, figsize=(12, 6.5))
    ax[0, 0].imshow(scene().astype(np.uint8)); ax[0, 0].set_title("scene")
    ax[0, 1].imshow(raw, cmap="gray", vmin=0, vmax=255); ax[0, 1].set_title("sensor (RGGB mosaic, "
                                                                            "WB error)")
    ax[0, 2].imshow(ref["rgb"].astype(np.uint8)); ax[0, 2].set_title("RTL debayer + WB (model)")
    ax[1, 0].imshow(res["ycc"][:, :, 0], cmap="gray", vmin=0, vmax=255); ax[1,
                                                                            0].set_title("Y (RTL)")
    ax[1, 1].imshow(res["edge"], cmap="gray", vmin=0, vmax=255); ax[1,
                                                                    1].set_title("edge map (RTL)")
    ax[1, 2].bar(range(256), res["hist"], width=1.0); ax[1, 2].set_title("Y histogram (RTL)"); ax[1,
        2].set_xlim(0, 255)
    for a in ax.flat[:5]:
        a.axis("off")
    fig.tight_layout()
    path = os.path.join(plot_dir, "an012_image_pipeline.png")
    fig.savefig(path, dpi=110)
    print(f"  plot -> {path}")

# Main ---------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="AN012 image pipeline.")
    parser.add_argument("--plot-dir", default=None, help="Save the figure here (matplotlib optional).")
    args = parser.parse_args()
    raw   = sensor(scene())
    beats = raster_beats(raw, 1)*2                                      # Two identical frames.
    ok = True
    results = None
    for name, thr, rr in (("free-flow", 0.0, 1.0), ("backpressure", 0.3, 0.6)):
        top = Pipeline()
        ref = reference(raw, top)
        out = simulate(top, beats, throttle=thr, ready_rate=rr)
        good, res = check(name, *out, ref, top)
        ok &= good
        results = results or res
    if args.plot_dir:
        plot(args.plot_dir, raw, ref, results)
    print("  PASS: YCbCr, edge map, histograms and latency gates met" if ok else "  FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
