#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""ADS-B / Mode-S preamble acquisition and 2 MHz pulse-position decode (AN006)."""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litedsp.comm.correlator import LiteDSPCorrelator
from test.common import column, run_stream

FS_MHZ = 2
PREAMBLE_PULSES = (0, 2, 7, 9)       # 0, 1, 3.5 and 4.5 us at 2 samples/us.
PREAMBLE_LEN = 16                     # 8 us.
FRAME_BITS = 112                      # Mode-S extended squitter.


def make_frame(seed=1090, amplitude=4000, sigma=300):
    rng = np.random.default_rng(seed)
    bits = rng.integers(0, 2, FRAME_BITS, dtype=np.int8)
    # DF17 (extended squitter) makes the synthetic payload recognizable.
    bits[:5] = [1, 0, 0, 0, 1]
    offset = 24
    x = rng.normal(0, sigma, offset + PREAMBLE_LEN + 2*FRAME_BITS + 20)
    for p in PREAMBLE_PULSES:
        x[offset + p] += amplitude
    for n, bit in enumerate(bits):
        x[offset + PREAMBLE_LEN + 2*n + (0 if bit else 1)] += amplitude
    return bits, offset, np.clip(np.rint(x), -32768, 32767).astype(int)


def run_receiver(x):
    # Zero-mean matched template rejects a steady noise floor and data with 50% duty cycle.
    template = np.full(PREAMBLE_LEN, -1/3, dtype=float)
    template[list(PREAMBLE_PULSES)] = 1.0
    dut = LiteDSPCorrelator(sequence=list(template), data_width=16, with_csr=False)
    cap = run_stream(dut, [{"i": int(v), "q": 0} for v in x], len(x),
        ["i", "q"], ["i", "q"], source_ready_rate=1.0)
    score = column(cap, "i", 16).astype(float)
    peak = int(np.argmax(score))
    start = peak - (PREAMBLE_LEN - 1)
    data = x[start + PREAMBLE_LEN:start + PREAMBLE_LEN + 2*FRAME_BITS]
    decoded = (data[0::2] > data[1::2]).astype(np.int8)
    sidelobes = np.delete(np.abs(score), np.arange(max(0, peak - 2), min(len(score), peak + 3)))
    margin_db = 20*np.log10(max(1.0, score[peak])/max(1.0, np.max(sidelobes)))
    return start, decoded, score, margin_db


def save_plot(path, x, score, offset):
    try:
        import matplotlib
    except ImportError:
        print("  (matplotlib not available: skipping plot)")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(path, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=140)
    ax.plot(x, lw=0.8, label="2 MHz magnitude samples")
    ax.axvline(offset, color="#1baf7a", label="detected preamble")
    ax.set(xlabel="sample", ylabel="ADC counts", title="AN006 ADS-B preamble and PPM frame")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(path, "an006_adsb.png"))
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plot-dir", default="doc/app_notes/img")
    args = parser.parse_args()
    bits, expected, x = make_frame()
    start, decoded, score, margin_db = run_receiver(x)
    errors = int(np.count_nonzero(decoded != bits))
    print(f"ADS-B receiver (AN006): preamble {start} (expected {expected}), "
          f"correlation margin {margin_db:.1f} dB, {errors}/{FRAME_BITS} bit errors")
    assert start == expected
    assert errors == 0
    assert margin_db >= 3.0
    assert list(decoded[:5]) == [1, 0, 0, 0, 1]
    save_plot(args.plot_dir, x, score, start)
    print("PASS: RTL matched filter found the Mode-S preamble and all 112 PPM bits decoded")


if __name__ == "__main__":
    main()
