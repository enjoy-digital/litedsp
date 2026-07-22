#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""CSS preamble acquisition, CFO estimation, and fixed-point FFT detector (AN008)."""

import argparse
import os
import sys

import numpy as np
from migen import passive

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litedsp.analysis.fft import LiteDSPFFT, bit_reverse
from litedsp.comm.cfo_est import LiteDSPCFOEstimator
from test.common import column, run_stream, to_signed

SF = 7
N = 1 << SF
PREAMBLE_SYMBOLS = 6
PREFIX_BLOCKS = 2
CFO_BINS = 1.35


def upchirp():
    n = np.arange(N)
    return np.exp(1j*np.pi*n*n/N)


def make_packet(symbols, amplitude=3500, sigma=1200, cfo_bins=CFO_BINS, seed=80):
    """Noise prefix + repeated zero-symbol preamble + payload, with continuous packet CFO."""
    rng = np.random.default_rng(seed)
    prefix = rng.normal(0, sigma, PREFIX_BLOCKS*N) + 1j*rng.normal(0, sigma, PREFIX_BLOCKS*N)
    blocks = []
    chirp = upchirp()
    for block, symbol in enumerate([0]*PREAMBLE_SYMBOLS + list(symbols)):
        local = np.arange(N)
        absolute = (PREFIX_BLOCKS + block)*N + local
        tx = amplitude*chirp*np.exp(2j*np.pi*symbol*local/N)
        tx *= np.exp(2j*np.pi*cfo_bins*absolute/N)
        tx += rng.normal(0, sigma, N) + 1j*rng.normal(0, sigma, N)
        blocks.append(tx)
    return np.concatenate([prefix] + blocks)


def acquire_preamble(rx):
    """Find PREAMBLE_SYMBOLS consecutive dechirped blocks with one common FFT peak."""
    blocks = np.asarray(rx).reshape(-1, N)
    spectra = np.abs(np.fft.fft(blocks*np.conj(upchirp()), axis=1))
    peaks = np.argmax(spectra, axis=1)
    second = np.partition(spectra, -2, axis=1)[:, -2]
    margins = 20*np.log10(np.maximum(1.0, spectra[np.arange(len(blocks)), peaks]) /
                          np.maximum(1.0, second))
    for start in range(len(blocks) - PREAMBLE_SYMBOLS + 1):
        sl = slice(start, start + PREAMBLE_SYMBOLS)
        if np.all(peaks[sl] == peaks[start]) and np.min(margins[sl]) >= 4.0:
            return start, int(peaks[start]), float(np.min(margins[sl]))
    raise RuntimeError("CSS preamble not found")


@passive
def _estimate_monitor(dut, estimates):
    while True:
        if (yield dut.estimate_ready):
            estimates.append((yield dut.angle))
        yield


def estimate_fractional_cfo(preamble):
    """Use the RTL delay-N autocorrelator/CORDIC to estimate CFO modulo one FFT bin."""
    samples = np.asarray(preamble)
    xi = np.clip(np.rint(samples.real), -32768, 32767).astype(int)
    xq = np.clip(np.rint(samples.imag), -32768, 32767).astype(int)
    dut = LiteDSPCFOEstimator(data_width=16, delay=N, span_log2=8,
        angle_width=16, with_csr=False)
    estimates = []
    run_stream(dut, [{"i": int(i), "q": int(q)} for i, q in zip(xi, xq)], len(xi),
        ["i", "q"], ["i", "q"], source_ready_rate=1.0,
        extra=[_estimate_monitor(dut, estimates)])
    if not estimates:
        raise RuntimeError("CFO estimator did not produce a result")
    signed = [int(to_signed(value, 16)) for value in estimates]
    return float(np.median(signed)/(1 << 16)), signed


def fft_detect(rx_symbol, cfo_bins):
    n = np.arange(N)
    corrected = np.asarray(rx_symbol)*np.conj(upchirp())*np.exp(-2j*np.pi*cfo_bins*n/N)
    xi = np.clip(np.rint(corrected.real), -32768, 32767).astype(int)
    xq = np.clip(np.rint(corrected.imag), -32768, 32767).astype(int)
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
    packet = make_packet(symbols)
    start, coarse, acquisition_margin = acquire_preamble(packet)
    preamble = packet[start*N:(start + PREAMBLE_SYMBOLS)*N]
    fractional, raw_estimates = estimate_fractional_cfo(preamble)
    cfo_estimate = coarse + fractional
    margins, spectra = [], []
    decoded = []
    payload_start = (start + PREAMBLE_SYMBOLS)*N
    for index, symbol in enumerate(symbols):
        rx_symbol = packet[payload_start + index*N:payload_start + (index + 1)*N]
        margin, peak, spectrum = fft_detect(rx_symbol, cfo_estimate)
        decoded.append(peak)
        margins.append(margin)
        spectra.append(spectrum)
    print(f"CSS receiver (AN008): SF{SF}, preamble block {start}, acquisition margin "
          f"{acquisition_margin:.1f} dB, CFO {cfo_estimate:.3f} bins "
          f"(truth {CFO_BINS:.2f}, RTL fractional estimates {raw_estimates}), "
          f"symbols {symbols} -> {decoded}, minimum FFT margin {min(margins):.1f} dB")
    assert start == PREFIX_BLOCKS
    assert abs(cfo_estimate - CFO_BINS) <= 0.05
    assert decoded == symbols
    assert min(margins) >= 12.0
    save_plot(args.plot_dir, spectra[1], symbols[1])
    print("PASS: acquired the CSS preamble, corrected RTL-estimated CFO, and decoded the packet")


if __name__ == "__main__":
    main()
