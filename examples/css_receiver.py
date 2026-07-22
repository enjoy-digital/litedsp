#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""CSS dechirp plus fixed-point FFT symbol detector (AN008)."""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litedsp.analysis.fft import LiteDSPFFT, bit_reverse
from test.common import column, run_stream

SF = 7
N = 1 << SF


def chirp_symbol(symbol, amplitude=3500, sigma=2000, cfo_bins=0.12, seed=0):
    rng = np.random.default_rng(seed)
    n = np.arange(N)
    up = np.exp(1j*np.pi*n*n/N)
    tx = amplitude*up*np.exp(2j*np.pi*(symbol + cfo_bins)*n/N)
    rx = tx + rng.normal(0, sigma, N) + 1j*rng.normal(0, sigma, N)
    dechirped = rx*np.conj(up)
    return np.clip(np.rint(dechirped.real), -32768, 32767).astype(int), \
        np.clip(np.rint(dechirped.imag), -32768, 32767).astype(int)


def fft_detect(symbol, seed=0):
    xi, xq = chirp_symbol(symbol, seed=seed)
    # Repetition supplies a steady complete FFT frame independent of SDF pipeline fill skew.
    dut = LiteDSPFFT(N=N, data_width=16, with_csr=False)
    samples = [{"i": int(i), "q": int(q)} for i, q in zip(np.tile(xi, 4), np.tile(xq, 4))]
    cap = run_stream(dut, samples, len(samples) - 1, ["i", "q"], ["i", "q"],
        source_ready_rate=1.0)
    out = column(cap, "i", 16) + 1j*column(cap, "q", 16)
    order = [bit_reverse(k, SF) for k in range(N)]
    # N-1 leading SDF fill beats precede the first complete spectrum. With four repeated
    # frames, the final N outputs are therefore one complete steady-state FFT frame.
    spectrum = np.abs(out[-N:][order]).astype(float)
    peak = int(np.argmax(spectrum))
    second = float(np.partition(spectrum, -2)[-2])
    margin = 20*np.log10(max(1.0, spectrum[peak])/max(1.0, second))
    return margin, peak, spectrum


def save_plot(path, spectrum, symbol):
    try:
        import matplotlib
    except ImportError:
        print("  (matplotlib not available: skipping plot)")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(path, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=140)
    db = 20*np.log10(spectrum/max(1.0, spectrum.max()) + 1e-6)
    ax.plot(db, lw=0.9)
    ax.axvline(symbol, color="#1baf7a", label=f"decoded symbol {symbol}")
    ax.set(xlabel="FFT bin / CSS symbol", ylabel="dB relative to peak", ylim=(-50, 3),
           title=f"AN008 SF{SF} dechirp spectrum")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(path, "an008_css.png"))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plot-dir", default="doc/app_notes/img")
    args = parser.parse_args()
    symbols = [3, 17, 64, 109]
    margins, spectra = [], []
    decoded = []
    for seed, symbol in enumerate(symbols):
        margin, peak, spectrum = fft_detect(symbol, seed=80 + seed)
        decoded.append(peak)
        margins.append(margin)
        spectra.append(spectrum)
    print(f"CSS receiver (AN008): SF{SF}, symbols {symbols} -> {decoded}, "
          f"minimum FFT margin {min(margins):.1f} dB")
    assert decoded == symbols
    assert min(margins) >= 12.0
    save_plot(args.plot_dir, spectra[1], symbols[1])
    print("PASS: fixed-point RTL FFT recovered every noisy dechirped CSS symbol")


if __name__ == "__main__":
    main()
