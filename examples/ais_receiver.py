#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""AIS 9600-baud GMSK discriminator and NRZI receive chain (AN007)."""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litedsp.comm.fm_demod import LiteDSPFMDemod
from test.common import column, run_stream

SPS = 4
BT = 0.4
PREAMBLE = np.tile([0, 1], 12).astype(np.int8)


def crc16_x25(bits):
    crc = 0xffff
    for bit in bits:
        mix = (crc ^ int(bit)) & 1
        crc >>= 1
        if mix:
            crc ^= 0x8408
    return crc ^ 0xffff


def fcs_bits(bits):
    value = crc16_x25(bits)
    return np.array([(value >> n) & 1 for n in range(16)], dtype=np.int8)


def nrzi_encode(bits, initial=1):
    out, level = [], initial
    for bit in bits:
        if bit == 0:                         # AIS/HDLC: zero causes a transition.
            level = -level
        out.append(level)
    return np.array(out, dtype=float)


def gmsk_modulate(bits, amplitude=12000, cfo=0.008, sigma=180, seed=162):
    levels = nrzi_encode(bits)
    nrz = np.repeat(levels, SPS)
    # Unit-area Gaussian pulse. This compact sampled form gives BT=0.4 smoothing and preserves
    # the MSK +/-pi/2 phase change per symbol after convolution.
    t = np.arange(-2*SPS, 2*SPS + 1)/SPS
    alpha = np.sqrt(2*np.log(2))/BT
    taps = np.exp(-0.5*(alpha*t)**2)
    taps /= taps.sum()
    shaped = np.convolve(nrz, taps, mode="same")
    dphi = shaped*(np.pi/(2*SPS)) + 2*np.pi*cfo
    phase = np.cumsum(dphi)
    rng = np.random.default_rng(seed)
    x = amplitude*np.exp(1j*phase)
    x += rng.normal(0, sigma, len(x)) + 1j*rng.normal(0, sigma, len(x))
    return np.clip(np.rint(x.real), -32768, 32767).astype(int), \
        np.clip(np.rint(x.imag), -32768, 32767).astype(int)


def discriminate(i, q):
    dut = LiteDSPFMDemod(data_width=16, angle_width=16, with_csr=False)
    cap = run_stream(dut, [{"i": int(a), "q": int(b)} for a, b in zip(i, q)], len(i),
        ["i", "q"], ["data"], source_ready_rate=1.0)
    return column(cap, "data", 16).astype(float)


def receive(freq, initial=1):
    # Remove the constant LO error, then integrate each known 4-sample symbol interval.
    centered = freq - np.median(freq)
    metrics = np.array([np.sum(centered[n:n + SPS]) for n in range(0, len(centered), SPS)])
    levels = np.where(metrics >= 0, 1, -1)
    prev = np.r_[initial, levels[:-1]]
    bits = (levels == prev).astype(np.int8)   # no transition => one, transition => zero.
    return bits, metrics


def save_plot(path, metrics, frame_start):
    try:
        import matplotlib
    except ImportError:
        print("  (matplotlib not available: skipping plot)")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(path, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=140)
    ax.plot(metrics, ".-", ms=3, lw=0.8)
    ax.axvspan(frame_start, frame_start + len(PREAMBLE), color="#1baf7a", alpha=0.2)
    ax.axhline(0, color="black", lw=0.6)
    ax.set(xlabel="symbol", ylabel="integrated discriminator", title="AN007 AIS GMSK decisions")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(os.path.join(path, "an007_ais.png"))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plot-dir", default="doc/app_notes/img")
    args = parser.parse_args()
    rng = np.random.default_rng(7)
    payload = rng.integers(0, 2, 96, dtype=np.int8)
    frame = np.r_[PREAMBLE, payload, fcs_bits(payload)]
    prefix = np.ones(12, dtype=np.int8)
    tx_bits = np.r_[prefix, frame, np.ones(8, dtype=np.int8)]
    i, q = gmsk_modulate(tx_bits)
    decoded, metrics = receive(discriminate(i, q))
    # Find the alternating training sequence in the recovered bit stream.
    scores = np.correlate(2*decoded - 1, 2*PREAMBLE - 1, mode="valid")
    start = int(np.argmax(scores))
    got = decoded[start + len(PREAMBLE):start + len(frame)]
    errors = int(np.count_nonzero(got != frame[len(PREAMBLE):]))
    got_payload = got[:len(payload)]
    got_fcs = got[len(payload):]
    crc_ok = np.array_equal(got_fcs, fcs_bits(got_payload))
    eye = float(np.min(np.abs(metrics[start:start + len(frame)])))
    print(f"AIS receiver (AN007): preamble symbol {start}, {errors} bit errors, "
          f"CRC {'OK' if crc_ok else 'FAIL'}, minimum eye {eye:.0f}")
    assert start == len(prefix)
    assert errors == 0 and crc_ok
    assert eye > 1000
    save_plot(args.plot_dir, metrics, start)
    print("PASS: RTL FM discriminator recovered the noisy AIS GMSK/NRZI frame and FCS")


if __name__ == "__main__":
    main()
