#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Chirp pulse-compression radar (AN004).

Chain: LiteDSPChirp (LFM pulse, captured from the actual hardware ROM/accumulator) -> simulated
target channel in NumPy (3 targets: delay + attenuation + AWGN) -> complex-tap matched filter
(the classic pulse compression: taps = time-reversed conjugate chirp, built from **two**
LiteDSPFIRFilterComplex instances since each applies real coefficients to I and Q) ->
LiteDSPMagnitude envelope -> host-side peak detection = range measurement.

Two chirp bandwidths are compared: range resolution (-3 dB mainlobe width) scales as ~1/B, and
the wideband config resolves a target pair the narrowband config merges. Peak-to-sidelobe
ratio is gated. Plots are written to doc/app_notes/ (or --plot-dir). Run:

    python3 examples/chirp_radar.py
"""

import os
import sys
import argparse

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litex.gen import LiteXModule

from litex.soc.interconnect import stream

from litedsp.common             import iq_layout
from litedsp.generation.source  import LiteDSPChirp
from litedsp.filter.fir         import LiteDSPFIRFilterComplex
from litedsp.analysis.magnitude import LiteDSPMagnitude

from test.common import run_stream, column

# Parameters ---------------------------------------------------------------------------------------

P       = 48                                  # Chirp pulse length (samples) = matched-filter taps.
SHIFT   = 20                                  # Matched-filter rescale (peak ~ a * P * FS / 2**SHIFT).
TARGETS = [(60, 0.7), (200, 0.5), (205, 0.4)]  # (delay, attenuation); last two closer than 1/B_narrow.
CONFIGS = [("wide", 0.50), ("narrow", 0.125)]  # (label, chirp bandwidth as a fraction of fs).
N_RX    = 340                                 # Received-channel length (covers last pulse + sidelobes).

# Chirp Pulse Capture ------------------------------------------------------------------------------

def capture_chirp(bandwidth):
    """Capture one P-sample LFM pulse (-B/2 -> +B/2) from the LiteDSPChirp hardware block."""
    dut = LiteDSPChirp(with_csr=False)
    dut.start.reset = (1 << 32) - int(round(bandwidth/2 * (1 << 32)))  # -B/2 (two's complement).
    dut.rate.reset  = int(round(bandwidth/P * (1 << 32)))              # B/P per sample.
    cap = run_stream(dut, None, P, [], ["i", "q"], source_ready_rate=1.0)
    return column(cap, "i", width=16) + 1j*column(cap, "q", width=16)

# Matched Filter -----------------------------------------------------------------------------------

class ChirpMatchedFilter(LiteXModule):
    """Complex-tap matched filter + envelope: pulse compression for a complex reference.

    ``LiteDSPFIRFilterComplex`` applies *real* coefficients to I and Q, so the complex-tap
    convolution ``y = h (*) x`` with ``h = conj(reversed(ref))`` is decomposed onto two of
    them: ``fir_re`` (taps Re(h)) and ``fir_im`` (taps Im(h)), recombined as
    ``y = (re.i - im.q) + j(re.q + im.i)``. A LiteDSPMagnitude then takes the envelope.
    """
    def __init__(self, reference, data_width=16, shift=SHIFT):
        n_taps = len(reference)
        # h = conj(time-reversed reference), already in Q1.15 counts from the chirp capture.
        h = np.conj(reference[::-1])
        self.fir_re = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=data_width,
            coefficients=[int(v) for v in h.real], shift=shift, with_csr=False)
        self.fir_im = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=data_width,
            coefficients=[int(v) for v in h.imag], shift=shift, with_csr=False)
        self.mag    = LiteDSPMagnitude(data_width=data_width + 1, with_csr=False)
        self.latency = self.fir_re.latency + self.mag.latency
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = self.mag.source

        # # #

        # Both FIRs are structurally identical -> lockstep (same pattern as inside
        # LiteDSPFIRFilterComplex for its I/Q pair).
        mid = stream.Endpoint(iq_layout(data_width + 1))
        self.comb += [
            self.fir_re.sink.valid.eq(self.sink.valid),
            self.fir_im.sink.valid.eq(self.sink.valid),
            self.fir_re.sink.i.eq(self.sink.i), self.fir_re.sink.q.eq(self.sink.q),
            self.fir_im.sink.i.eq(self.sink.i), self.fir_im.sink.q.eq(self.sink.q),
            self.sink.ready.eq(self.fir_re.sink.ready & self.fir_im.sink.ready),
            mid.valid.eq(self.fir_re.source.valid & self.fir_im.source.valid),
            mid.i.eq(self.fir_re.source.i - self.fir_im.source.q),
            mid.q.eq(self.fir_re.source.q + self.fir_im.source.i),
            self.fir_re.source.ready.eq(mid.ready),
            self.fir_im.source.ready.eq(mid.ready),
            mid.connect(self.mag.sink),
        ]

# Target Channel -----------------------------------------------------------------------------------

def target_channel(pulse, targets, n, sigma=250.0, seed=7):
    """Delay + attenuate the pulse per target, add AWGN; return int I/Q sample dicts."""
    rng = np.random.default_rng(seed)
    rx  = rng.normal(0, sigma, n) + 1j*rng.normal(0, sigma, n)
    for delay, a in targets:
        rx[delay:delay + len(pulse)] += a*pulse
    rx = np.round(rx)
    assert np.abs(rx.real).max() < 32768 and np.abs(rx.imag).max() < 32768
    return [{"i": int(v), "q": int(w)} for v, w in zip(rx.real, rx.imag)]

# Measurements -------------------------------------------------------------------------------------

def find_peaks(env, threshold, min_sep=4):
    """Local maxima above ``threshold``, collapsed to the largest within ``min_sep``."""
    idx = [k for k in range(1, len(env) - 1)
           if env[k] >= env[k-1] and env[k] > env[k+1] and env[k] >= threshold]
    peaks = []
    for k in idx:
        if peaks and k - peaks[-1] < min_sep:
            if env[k] > env[peaks[-1]]:
                peaks[-1] = k
        else:
            peaks.append(k)
    return peaks

def mainlobe_width(env, peak):
    """-3 dB width (samples) around ``peak``, linearly interpolated."""
    half = env[peak]/np.sqrt(2)
    l = peak
    while l > 0 and env[l] > half:
        l -= 1
    r = peak
    while r < len(env) - 1 and env[r] > half:
        r += 1
    # Interpolate the exact crossings.
    xl = l + (half - env[l])/(env[l+1] - env[l])
    xr = r - (half - env[r])/(env[r-1] - env[r])
    return xr - xl

def pslr_db(env, peak, guard, span=45):
    """Peak-to-sidelobe ratio (dB) in ``peak +- span``, excluding the ``+- guard`` mainlobe.

    ``guard`` should be the first correlation null, ceil(1/B) samples, so the first sidelobe
    is included in the measurement.
    """
    lo, hi = max(0, peak - span), min(len(env), peak + span + 1)
    window = np.array(env[lo:hi], dtype=float)
    window[max(0, peak - guard - lo):peak + guard + 1 - lo] = 0
    return 20*np.log10(env[peak]/window.max())

# Plots --------------------------------------------------------------------------------------------

def save_plots(plot_dir, results, offset):
    try:
        import matplotlib
    except ImportError:
        print("  (matplotlib not available: skipping plots)")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(plot_dir, exist_ok=True)
    ink, muted = "#333230", "#6f6d66"
    colors     = {"wide": "#2a78d6", "narrow": "#1baf7a"}

    def style(ax):
        ax.grid(color="#dddbd4", lw=0.6, alpha=0.6)
        ax.tick_params(colors=muted, labelsize=8)
        for s in ax.spines.values():
            s.set_color("#c9c7c0")

    # Compressed pulses: one panel per bandwidth, true delays annotated.
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.2), dpi=140, sharex=True)
    for ax, (label, B) in zip(axes, CONFIGS):
        env   = results[label]["env"]
        env_db = 20*np.log10(env/env.max() + 1e-9)
        delay  = np.arange(len(env)) - offset            # Output index -> range delay (samples).
        ax.plot(delay, env_db, color=colors[label], lw=1.6,
            label=f"{label}: B = {B:.3g} fs (BT = {B*P:.0f})")
        for d, a in TARGETS:
            ax.axvline(d, color="#c9c7c0", lw=0.8, ls=":")
        ax.annotate("60", (TARGETS[0][0], 1), fontsize=8, color=muted, ha="center",
            annotation_clip=False)
        ax.annotate("200 / 205", (202.5, 1), fontsize=8, color=muted, ha="center",
            annotation_clip=False)
        ax.set_ylabel("envelope (dB)", color=ink)
        ax.set_ylim(-45, 6)
        ax.set_xlim(0, len(env) - offset - 1)
        style(ax)
        ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
        ax.text(0.98, 0.88, f"PSLR {results[label]['pslr']:.1f} dB", transform=ax.transAxes,
            ha="right", fontsize=8, color=ink)
    axes[0].set_title("AN004 pulse compression: matched-filter envelope, targets at 60/200/205",
        color=ink, fontsize=11)
    axes[1].set_xlabel("range delay (samples)", color=ink)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an004_compression.png"))
    plt.close(fig)

    # Resolution zoom on the close pair (wide resolves, narrow merges).
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=140)
    for label, B in CONFIGS:
        env    = results[label]["env"]
        env_db = 20*np.log10(env/env.max() + 1e-9)
        delay  = np.arange(len(env)) - offset
        w      = results[label]["width"]
        ax.plot(delay, env_db, color=colors[label], lw=1.8,
            label=f"{label}: -3 dB width {w:.1f} samples")
    for d, a in TARGETS[1:]:
        ax.axvline(d, color="#c9c7c0", lw=0.8, ls=":")
    ax.annotate("targets @ 200 & 205", (208, 2), fontsize=8, color=muted, ha="left",
        annotation_clip=False)
    ax.axhline(-3, color=muted, lw=0.9, ls="--")
    ax.text(228, -2.5, "-3 dB", fontsize=8, color=muted)
    ax.set_xlim(180, 230)
    ax.set_ylim(-30, 6)
    ax.set_xlabel("range delay (samples)", color=ink)
    ax.set_ylabel("envelope (dB)", color=ink)
    ax.set_title("AN004 range resolution: the 5-sample pair, wide vs narrow chirp",
        color=ink, fontsize=11)
    style(ax)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an004_resolution.png"))
    plt.close(fig)
    print(f"  plots -> {os.path.join(plot_dir, 'an004_compression.png')}, "
          f"{os.path.join(plot_dir, 'an004_resolution.png')}")

# Demo ---------------------------------------------------------------------------------------------

def main():
    default_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "doc", "app_notes")
    parser = argparse.ArgumentParser(description="AN004 chirp pulse-compression radar.")
    parser.add_argument("--plot-dir", default=default_dir, help="Output directory for PNG plots.")
    args = parser.parse_args()

    results = {}
    offset  = None
    print(f"Chirp radar: P={P}-sample LFM pulse, targets (delay, a) = {TARGETS}")
    for label, B in CONFIGS:
        pulse   = capture_chirp(B)
        samples = target_channel(pulse, TARGETS, N_RX)
        dut     = ChirpMatchedFilter(pulse)
        # Sample-index alignment: the FIR/magnitude pipeline emits one output per input (their
        # declared `latency` is cycle-domain fill, absorbed by the valid pipeline), so target d
        # peaks at output sample d + (P-1) — the full-overlap lag of the correlation.
        offset  = P - 1
        cap = run_stream(dut, samples, N_RX - 2*dut.latency, ["i", "q"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        env = column(cap, "data").astype(float)

        peaks = find_peaks(env, threshold=0.25*env.max())
        width = mainlobe_width(env, TARGETS[0][0] + offset)
        pslr  = pslr_db(env, TARGETS[0][0] + offset, guard=int(np.ceil(1/B)))
        results[label] = {"env": env, "peaks": peaks, "width": width, "pslr": pslr}
        print(f"  {label:6s} B={B:5.3f} fs (BT={B*P:4.1f}): peaks at "
              f"{[p - offset for p in peaks]} (true {[d for d, _ in TARGETS]}), "
              f"-3 dB width {width:.2f} samples (theory ~{0.886/B:.2f}), PSLR {pslr:.1f} dB")

    # Assertions.
    wide, narrow = results["wide"], results["narrow"]
    # 1. Wideband: every injected delay recovered exactly (the peak of target d sits at
    #    output sample d + (P-1)).
    assert [p - offset for p in wide["peaks"]] == [d for d, _ in TARGETS], \
        f"wideband peaks {[p - offset for p in wide['peaks']]} != {[d for d, _ in TARGETS]}"
    # 2. Narrowband: the isolated target is exact, the 5-sample pair merges into one return.
    assert narrow["peaks"][0] - offset == TARGETS[0][0], "narrowband isolated target mispositioned"
    assert len(narrow["peaks"]) == 2, \
        f"narrowband should merge the close pair (got {len(narrow['peaks'])} peaks)"
    # 3. Resolution improves with bandwidth (theory: width ~ 0.886/B, i.e. 4x here).
    assert wide["width"] < 0.5*narrow["width"], \
        f"wideband width {wide['width']:.2f} not < half of narrowband {narrow['width']:.2f}"
    # 4. Sidelobe gate: rectangular-weighted LFM PSLR is ~13.2 dB for large BT; gate wideband
    #    (BT=24) at 10 dB (envelope uses the alpha-max-beta-min approximation, ~+-1 dB).
    assert wide["pslr"] >= 10.0, f"wideband PSLR {wide['pslr']:.1f} dB < 10 dB"
    print(f"  PASS: all wideband delays exact, close pair resolved only at high B, "
          f"resolution x{narrow['width']/wide['width']:.1f} with 4x bandwidth, "
          f"PSLR {wide['pslr']:.1f} dB")

    save_plots(args.plot_dir, results, offset)

if __name__ == "__main__":
    main()
