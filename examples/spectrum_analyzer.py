#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Streaming spectrum analyzer assembled from LiteDSP analysis blocks.

Chain: Window (Hann) -> FFT (radix-2 SDF) -> PSD (|X|^2 averaged over frames). Feeds two
complex tones and prints the averaged power spectrum peaks. Run:

    python3 examples/spectrum_analyzer.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common         import iq_layout, real_layout
from litedsp.analysis.window import LiteDSPWindow
from litedsp.analysis.fft    import LiteDSPFFT
from litedsp.analysis.psd    import LiteDSPPSD

from test.common import run_stream, column

# Spectrum Analyzer --------------------------------------------------------------------------------

class SpectrumAnalyzer(LiteXModule):
    def __init__(self, N=256, data_width=16, avg_log2=2, window="hann"):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(real_layout(2*data_width + avg_log2))

        # # #

        self.window = LiteDSPWindow(N, data_width=data_width, window=window, with_csr=False)
        self.fft    = LiteDSPFFT(N, data_width=data_width, with_csr=False)
        self.psd    = LiteDSPPSD(N, fft_latency=self.fft.latency, data_width=data_width,
            avg_log2=avg_log2, with_csr=False)
        self.comb += [
            self.sink.connect(self.window.sink),
            self.window.source.connect(self.fft.sink),
            self.fft.source.connect(self.psd.sink),
            self.psd.source.connect(self.source),
        ]

# Demo ---------------------------------------------------------------------------------------------

def main():
    N, avg_log2 = 256, 2
    dut = SpectrumAnalyzer(N=N, avg_log2=avg_log2)

    # Two equal complex tones at bins 40 and 100.
    tones = [40, 100]
    t   = np.arange(N)
    sig = sum(8000*np.exp(2j*np.pi*b*t/N) for b in tones)
    fi  = np.round(sig.real).astype(int)
    fq  = np.round(sig.imag).astype(int)
    nfr = (1 << avg_log2) + 4
    xi  = list(fi)*nfr
    xq  = list(fq)*nfr
    samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))]

    cap  = run_stream(dut, samples, N, ["i", "q"], ["data"],
        sink_throttle=0.0, source_ready_rate=1.0)
    spec    = column(cap, "data").astype(float)
    spec_db = 10*np.log10(spec/spec.max() + 1e-12)
    # Noise floor = median of bins away from the tones.
    mask = np.ones(N, bool)
    for b in tones:
        mask[max(0, b-2):b+3] = False
    floor_db = 10*np.log10(np.median(spec[mask])/spec.max() + 1e-12)
    print(f"Spectrum analyzer: N={N}, {1 << avg_log2} averages")
    print(f"  noise floor ~ {floor_db:6.1f} dBFS")
    for b in tones:
        print(f"    tone bin {b:3d}: {spec_db[b]:6.1f} dBFS  ({spec_db[b]-floor_db:5.1f} dB above floor)")

if __name__ == "__main__":
    main()
