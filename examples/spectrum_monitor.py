#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Timestamped spectrum monitor with waterfall (AN003).

Chain: LiteDSPTimeCore + LiteDSPTimestamper (absolute ingress time) -> LiteDSPTimeUntagger ->
LiteDSPWelchPSD (Hann window -> FFT -> PSD, 50% segment overlap). The PSD accumulator runs in
two modes on the same stimulus (two tones + a transient chirp burst + noise):

- linear average (``PSD_MODE_LINEAR``): successive spectra -> host-side waterfall;
- max-hold (``PSD_MODE_MAX``): per-bin peak trace that captures the transient chirp the
  averaged trace smears.

Ingress timestamps (tagged before the elastic Welch replay stalls) give the waterfall an
*absolute* sample-time axis; see doc/timestamps.md for the sum-of-latency back-computation.
Plots (waterfall + averaged/max-hold overlay) are written to doc/app_notes/ (or --plot-dir).
Run:

    python3 examples/spectrum_monitor.py
"""

import os
import sys
import argparse

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import passive

from litex.gen import LiteXModule

from litedsp.stream.timestamp import LiteDSPTimeCore, LiteDSPTimestamper, LiteDSPTimeUntagger
from litedsp.analysis.welch   import LiteDSPWelchPSD
from litedsp.analysis.psd     import PSD_MODE_LINEAR, PSD_MODE_MAX

from test.common import run_stream, column

# Parameters ---------------------------------------------------------------------------------------

N          = 64                    # FFT size (bins).
AVG_LOG2   = 1                     # 2 windowed segments averaged per emitted spectrum.
OVERLAP    = 50                    # Welch segment overlap (percent).
STEP       = N*(100 - OVERLAP)//100   # New input samples per segment.
ROW_STEP   = (1 << AVG_LOG2)*STEP  # New input samples per emitted spectrum (waterfall row).
EPOCH      = 1_000_000             # Host-set TimeCore epoch (absolute time origin).

TONE_BINS  = [9, 23]               # CW tones (always present).
CHIRP_SPAN = (36, 56)              # Chirp sweep, in bins.
CHIRP_TIME = (560, 880)            # Chirp burst, in input samples.

# Spectrum Monitor ---------------------------------------------------------------------------------

class SpectrumMonitor(LiteXModule):
    """Timestamper -> TimeUntagger -> WelchPSD(overlap): a timestamped spectrum monitor."""
    def __init__(self, N=64, data_width=16, avg_log2=1, overlap=50, window="hann", epoch=0):
        self.time_core   = LiteDSPTimeCore(with_csr=False)
        self.timestamper = LiteDSPTimestamper(data_width=data_width, with_csr=False)
        self.untag       = LiteDSPTimeUntagger(data_width=data_width)
        self.welch       = LiteDSPWelchPSD(N=N, data_width=data_width, avg_log2=avg_log2,
            window=window, overlap=overlap, with_csr=False)
        self.time_core.count.reset = epoch  # Host disciplines the epoch (CSR set_time on hardware).
        self.sink   = self.timestamper.sink
        self.source = self.welch.source
        self.comb += [
            self.timestamper.time.eq(self.time_core.count),
            self.timestamper.source.connect(self.untag.sink),
            self.untag.source.connect(self.welch.sink),
        ]

# Stimulus -----------------------------------------------------------------------------------------

def make_stimulus(n):
    """Two CW tones + a transient chirp burst + noise (deterministic)."""
    rng = np.random.default_rng(42)
    t   = np.arange(n)
    sig = sum(6000*np.exp(2j*np.pi*b*t/N) for b in TONE_BINS).astype(complex)
    # Chirp burst: bins CHIRP_SPAN[0] -> CHIRP_SPAN[1] during CHIRP_TIME.
    t0, t1 = CHIRP_TIME
    tb     = np.arange(t1 - t0)
    fb     = (CHIRP_SPAN[0] + (CHIRP_SPAN[1] - CHIRP_SPAN[0])*tb/(t1 - t0))/N
    sig[t0:t1] += 5000*np.exp(2j*np.pi*np.cumsum(fb))
    sig += rng.normal(0, 60, n) + 1j*rng.normal(0, 60, n)
    return [{"i": int(v), "q": int(w)} for v, w in zip(np.round(sig.real), np.round(sig.imag))]

# Probes -------------------------------------------------------------------------------------------

@passive
def timestamp_probe(endpoint, out):
    """Record the ``timestamp`` param of every sample accepted at ``endpoint``."""
    while True:
        if (yield endpoint.valid) and (yield endpoint.ready):
            out.append((yield endpoint.timestamp))
        yield

# Runs ---------------------------------------------------------------------------------------------

def run_monitor(mode, n_rows, samples):
    """Elaborate + simulate one monitor run; return (spectra[n_rows][N], ingress timestamps)."""
    dut = SpectrumMonitor(N=N, avg_log2=AVG_LOG2, overlap=OVERLAP, epoch=EPOCH)
    dut.welch.psd.mode.reset = mode  # Static per run (CSR psd_control.mode on hardware).
    ts  = []
    cap = run_stream(dut, samples, n_rows*N, ["i", "q"], ["data"],
        sink_throttle=0.0, source_ready_rate=1.0,
        extra=[timestamp_probe(dut.timestamper.source, ts)])
    return column(cap, "data").astype(float).reshape(n_rows, N), np.array(ts), dut

# Plots --------------------------------------------------------------------------------------------

def save_plots(plot_dir, wf_db, row_ts, avg_db, maxhold_db, floor_db, peaks):
    try:
        import matplotlib
    except ImportError:
        print("  (matplotlib not available: skipping plots)")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    os.makedirs(plot_dir, exist_ok=True)
    ink, muted = "#333230", "#6f6d66"
    cmap = LinearSegmentedColormap.from_list("litedsp_blue",
        ["#f8fafd", "#cde2fb", "#86b6ef", "#3987e5", "#256abf", "#184f95", "#0d366b"])

    # Waterfall (absolute sample-time axis from the ingress timestamps).
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=140)
    im = ax.imshow(wf_db, aspect="auto", origin="lower", cmap=cmap,
        vmin=floor_db - 6, vmax=0, interpolation="nearest",
        extent=[-0.5, N - 0.5, -0.5, wf_db.shape[0] - 0.5])
    yticks = range(0, wf_db.shape[0], 4)
    ax.set_yticks(list(yticks), [f"{row_ts[m]:,}" for m in yticks])
    ax.set_xlabel("FFT bin (natural order)", color=ink)
    ax.set_ylabel("ingress time (TimeCore count)", color=ink)
    ax.set_title(f"AN003 waterfall: WelchPSD N={N}, {1 << AVG_LOG2} avg, {OVERLAP}% overlap",
        color=ink, fontsize=11)
    ax.tick_params(colors=muted, labelsize=8)
    for b in TONE_BINS:
        ax.annotate(f"tone {b}", (b, wf_db.shape[0] - 1.2), ha="center", va="top",
            fontsize=8, color="white", rotation=90)
    cb = fig.colorbar(im, ax=ax, pad=0.02)
    cb.set_label("dB (rel. max)", color=ink, fontsize=9)
    cb.ax.tick_params(colors=muted, labelsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an003_waterfall.png"))
    plt.close(fig)

    # Averaged spectrum + max-hold overlay, detected peaks annotated.
    fig, ax = plt.subplots(figsize=(7.2, 3.8), dpi=140)
    bins = np.arange(N)
    ax.axvspan(CHIRP_SPAN[0], CHIRP_SPAN[1], color="#eceae4", zorder=0)
    ax.text(sum(CHIRP_SPAN)/2, 2, "chirp band", ha="center", fontsize=8, color=muted)
    ax.plot(bins, maxhold_db, color="#1baf7a", lw=1.8, label="max-hold (PSD_MODE_MAX)")
    ax.plot(bins, avg_db,     color="#2a78d6", lw=1.8, label="average (PSD_MODE_LINEAR)")
    ax.axhline(floor_db, color=muted, lw=1.0, ls="--")
    ax.text(N - 1, floor_db + 1, "noise floor", ha="right", fontsize=8, color=muted)
    for b in peaks:
        ax.annotate(f"bin {b}: {avg_db[b]:.1f} dB".replace("-0.0 ", "0.0 "), (b, avg_db[b]),
            xytext=(b + 2.0, avg_db[b] - 14), fontsize=8, color=ink,
            arrowprops=dict(arrowstyle="-", color=muted, lw=0.8))
        ax.plot([b], [avg_db[b]], "o", ms=5, color="#2a78d6", mec="white", mew=1.0)
    ax.set_xlabel("FFT bin (natural order)", color=ink)
    ax.set_ylabel("dB (rel. max)", color=ink)
    ax.set_title("AN003 spectrum: average smears the chirp, max-hold captures it",
        color=ink, fontsize=11)
    ax.set_xlim(0, N - 1)
    ax.set_ylim(floor_db - 8, 6)
    ax.grid(color="#dddbd4", lw=0.6, alpha=0.6)
    ax.tick_params(colors=muted, labelsize=8)
    for s in ax.spines.values():
        s.set_color("#c9c7c0")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an003_spectrum.png"))
    plt.close(fig)
    print(f"  plots -> {os.path.join(plot_dir, 'an003_waterfall.png')}, "
          f"{os.path.join(plot_dir, 'an003_spectrum.png')}")

# Demo ---------------------------------------------------------------------------------------------

def main():
    default_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "doc", "app_notes")
    parser = argparse.ArgumentParser(description="AN003 spectrum monitor with waterfall.")
    parser.add_argument("--plot-dir", default=default_dir, help="Output directory for PNG plots.")
    args = parser.parse_args()

    n_rows  = 20                   # Waterfall rows (linear-average run).
    n_hold  = 16                   # Spectra of the max-hold run (last one = cumulative peak).
    samples = make_stimulus(1500)

    print(f"Spectrum monitor: N={N}, {1 << AVG_LOG2} avg/spectrum, {OVERLAP}% overlap, "
          f"epoch={EPOCH:,}")

    # Run 1: linear average -> waterfall.
    wf, ts, dut = run_monitor(PSD_MODE_LINEAR, n_rows, samples)
    # Run 2: max-hold on the same stimulus -> cumulative per-bin peak trace.
    hold, _, _ = run_monitor(PSD_MODE_MAX, n_hold, samples)
    maxhold = hold[-1]

    # Sum-of-latency bookkeeping (doc/timestamps.md): fixed-latency prefix of the chain.
    lat = [("timestamper", dut.timestamper.latency), ("untag", dut.untag.latency),
           ("window", dut.welch.window.latency), ("fft", dut.welch.fft.latency)]
    print("  chain latencies: " + " + ".join(f"{n}={v}" for n, v in lat)
          + f" = {sum(v for _, v in lat)} samples (PSD is frame-accumulating: variable)")

    # Waterfall row m averages segments 2m..2m+1 = ingress samples [m*ROW_STEP, m*ROW_STEP+96).
    row_ts = ts[np.arange(n_rows)*ROW_STEP]
    assert np.all(np.diff(ts) >= 1), "ingress timestamps must be strictly increasing"
    stalls = int(ts[-1] - ts[0]) - (len(ts) - 1)
    print(f"  ingress: first sample @ {ts[0]:,}, {stalls} stall cycles absorbed over "
          f"{len(ts)} samples (Welch replay + PSD readout)")

    # dB views (common reference = waterfall max).
    ref        = wf.max()
    wf_db      = 10*np.log10(wf/ref + 1e-12)
    avg        = wf.mean(axis=0)
    avg_db     = 10*np.log10(avg/ref + 1e-12)
    maxhold_db = 10*np.log10(maxhold/ref + 1e-12)

    # Detected peaks (host-side argmax per exclusion zone: LiteDSPPeakBin conventions —
    # natural bin order, per-frame argmax).
    mask  = np.ones(N, bool)
    peaks = []
    for _ in range(len(TONE_BINS)):
        b = int(np.argmax(np.where(mask, avg, -np.inf)))
        peaks.append(b)
        mask[max(0, b - 2):b + 3] = False
    peaks = sorted(peaks)
    band     = np.arange(CHIRP_SPAN[0] + 2, CHIRP_SPAN[1] - 1)  # Interior of the chirp sweep.
    mask[band] = False
    floor_db = 10*np.log10(np.median(avg[mask])/ref + 1e-12)
    print(f"  noise floor ~ {floor_db:6.1f} dB")
    for b, tone in zip(peaks, TONE_BINS):
        print(f"    detected peak bin {b:2d} (injected {tone:2d}): {avg_db[b]:6.1f} dB")

    # Chirp-band contrast: max-hold holds the transient, the average smears it.
    delta = np.median(maxhold_db[band] - avg_db[band])
    print(f"  chirp band bins {band[0]}..{band[-1]}: max-hold - average = {delta:.1f} dB (median), "
          f"max-hold min = {maxhold_db[band].min():.1f} dB vs floor {floor_db:.1f} dB")

    # Chirp onset in absolute time from the waterfall (timestamped rows).
    band_db  = 10*np.log10(wf[:, band].mean(axis=1)/ref + 1e-12)
    onset    = int(np.argmax(band_db > floor_db + 10))
    true_ts  = ts[CHIRP_TIME[0]]
    print(f"  chirp onset: row {onset} @ {row_ts[onset]:,} (true ingress {true_ts:,}, "
          f"row covers {ROW_STEP} + overlap samples)")

    # Assertions.
    assert peaks == sorted(TONE_BINS), f"tone bins {sorted(TONE_BINS)} not recovered: {peaks}"
    assert maxhold_db[band].min() >= floor_db + 10, "max-hold lost the chirp transient"
    assert delta >= 6, f"max-hold does not stand out of the average in the chirp band ({delta:.1f} dB)"
    # Onset row covers the true burst start within one row of slack.
    lo, hi = (onset - 1)*ROW_STEP, onset*ROW_STEP + STEP + N
    assert lo <= CHIRP_TIME[0] < hi, f"chirp onset row {onset} does not cover sample {CHIRP_TIME[0]}"
    print("  PASS: tones within a bin, max-hold captures the chirp the average smears, "
          "onset located in absolute time")

    save_plots(args.plot_dir, wf_db, row_ts, avg_db, maxhold_db, floor_db, peaks)

if __name__ == "__main__":
    main()
