#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""QPSK receiver example: RRC matched filter -> symbol timing recovery -> slicer.

Demonstrates the full symbol-synchronization chain on a pulse-shaped QPSK signal with a timing
offset.  python3 examples/qpsk_rx.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common               import iq_layout
from litedsp.filter.fir           import LiteDSPFIRFilterComplex
from litedsp.comm.timing_recovery import LiteDSPTimingRecovery
from litedsp.comm.slicer          import LiteDSPSlicer
from litedsp.filter.design        import rrc_coefficients

from test.common import run_stream, column, to_signed

# QPSK receiver chain ------------------------------------------------------------------------------

class QPSKReceiver(LiteXModule):
    def __init__(self, data_width=16, sps=2, span=8, beta=0.35):
        self.sink = stream.Endpoint(iq_layout(data_width))

        # # #

        self.mf = LiteDSPFIRFilterComplex(n_taps=sps*span + 1, data_width=data_width,
            coefficients=rrc_coefficients(sps, span, beta, data_width=data_width), with_csr=False)
        self.timing = LiteDSPTimingRecovery(data_width=data_width, sps=sps, gain_mu=0.1, with_csr=False)
        self.slicer = LiteDSPSlicer(data_width=data_width, bits_per_axis=1, spacing=4000, with_csr=False)
        self.source = self.slicer.source
        self.comb += [
            self.sink.connect(self.mf.sink),
            self.mf.source.connect(self.timing.sink),
            self.timing.source.connect(self.slicer.sink),
        ]

def main():
    L, sps, span, beta = 900, 2, 8, 0.35
    rng = np.random.RandomState(2)
    d   = (2*rng.randint(0, 2, L) - 1) + 1j*(2*rng.randint(0, 2, L) - 1)

    # TX: RRC pulse-shaped QPSK at `sps` samples/symbol, with a fractional timing offset.
    sps_hi = 32
    up = np.zeros(L*sps_hi, complex); up[::sps_hi] = d
    rrc = np.array(rrc_coefficients(sps_hi, span, beta))/32768.0
    sig = np.convolve(up, rrc)/np.max(np.abs(np.convolve(up, rrc)))
    x = np.round(sig[9::sps_hi//sps]*11000).astype(complex)   # 2 sps + timing offset.

    dut = QPSKReceiver(data_width=16, sps=sps, span=span, beta=beta)
    samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
    cap = run_stream(dut, samples, len(x)//sps - 20, ["i", "q"], ["i", "q", "symbol"],
        sink_throttle=0.0, source_ready_rate=1.0)
    gi = to_signed(column(cap, "i"), 16); gq = to_signed(column(cap, "q"), 16)

    # SER vs TX (post-lock segment, search alignment + QPSK sign ambiguity).
    seg_r = np.sign(gi[len(gi)//2:len(gi)//2 + 200]).astype(int)
    seg_q = np.sign(gq[len(gq)//2:len(gq)//2 + 200]).astype(int)
    di, dq = np.sign(d.real).astype(int), np.sign(d.imag).astype(int)
    best = 1.0
    for off in range(len(d) - len(seg_r)):
        for si in (1, -1):
            for sq in (1, -1):
                best = min(best, 0.5*(np.mean(seg_r != si*di[off:off+len(seg_r)]) +
                                      np.mean(seg_q != sq*dq[off:off+len(seg_q)])))
    print(f"QPSK RX: matched filter -> timing recovery -> slicer ({len(gi)} symbols)")
    print(f"  symbol-error-rate vs TX: {best:.4f}")

if __name__ == "__main__":
    main()
