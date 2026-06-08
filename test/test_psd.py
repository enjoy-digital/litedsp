#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.analysis.fft import FFT
from litedsp.analysis.psd import PSD

from test.common import run_stream, column

class _FFTPSD(LiteXModule):
    def __init__(self, N, data_width=16, avg_log2=2):
        self.fft = FFT(N, data_width=data_width, with_csr=False)
        self.psd = PSD(N, latency=self.fft.latency, data_width=data_width,
            avg_log2=avg_log2, with_csr=False)
        self.comb += self.fft.source.connect(self.psd.sink)
        self.sink   = self.fft.sink
        self.source = self.psd.source

class TestPSD(unittest.TestCase):
    def test_tone_spectrum(self):
        N, avg_log2 = 64, 2
        k0  = 11
        t   = np.arange(N)
        fi  = np.round(9000*np.cos(2*np.pi*k0*t/N)).astype(int)
        fq  = np.round(9000*np.sin(2*np.pi*k0*t/N)).astype(int)
        # Enough input for the skip + accumulation of one spectrum (+margin).
        nfr     = (1 << avg_log2) + 3
        xi      = list(fi)*nfr + list(fi)  # extra margin
        xq      = list(fq)*nfr + list(fq)
        dut     = _FFTPSD(N, data_width=16, avg_log2=avg_log2)
        samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))]
        cap     = run_stream(dut, samples, N, ["i", "q"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        spec = column(cap, "data")           # One spectrum (natural bin order).
        self.assertEqual(len(spec), N)
        self.assertEqual(int(np.argmax(spec)), k0)
        self.assertGreater(spec[k0]/max(np.sort(spec)[-2], 1), 100.0)  # >20 dB above next bin.

    def test_backpressure(self):
        N, avg_log2 = 64, 2
        k0  = 5
        t   = np.arange(N)
        fi  = np.round(9000*np.cos(2*np.pi*k0*t/N)).astype(int)
        fq  = np.round(9000*np.sin(2*np.pi*k0*t/N)).astype(int)
        nfr = (1 << avg_log2) + 4
        xi  = list(fi)*nfr
        xq  = list(fq)*nfr
        dut = _FFTPSD(N, data_width=16, avg_log2=avg_log2)
        samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))]
        cap = run_stream(dut, samples, N, ["i", "q"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.6)
        spec = column(cap, "data")
        self.assertEqual(int(np.argmax(spec)), k0)

if __name__ == "__main__":
    unittest.main()
