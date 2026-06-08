#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.analysis.fft       import FFT, bit_reverse
from litedsp.stream.convert     import OffsetBinaryToTwos, TwosToOffsetBinary
from litedsp.analysis.goertzel  import Goertzel
from litedsp.comm.correlator    import Correlator
from litedsp.correction.iq_balance import IQBalance

from test.common import run_stream, column, to_signed, snr_db

class TestIFFT(unittest.TestCase):
    def test_matches_numpy(self):
        N, bits = 64, 6
        rng = np.random.RandomState(0)
        X = (rng.randint(-6000, 6000, N) + 1j*rng.randint(-6000, 6000, N))
        dut = FFT(N=N, data_width=16, inverse=True, with_csr=False)
        samples = [{"i": int(X[k].real), "q": int(X[k].imag)} for k in range(N)]*5
        cap = run_stream(dut, samples, len(samples) - 1, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        out = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        ref = np.fft.ifft(X)
        best = -np.inf
        for off in range(len(out) - N):
            nat = np.array([out[off:off + N][bit_reverse(k, bits)] for k in range(N)])
            best = max(best, snr_db(ref, nat))
        self.assertGreater(best, 40.0)

class TestConvert(unittest.TestCase):
    def test_offset_binary_roundtrip(self):
        prng = random.Random(1)
        xi = [prng.randint(-30000, 30000) for _ in range(64)]
        xq = [prng.randint(-30000, 30000) for _ in range(64)]
        dut = OffsetBinaryToTwos(data_width=16)
        # Feed offset-binary (signed+32768) -> expect signed back.
        ob = [{"i": (xi[k] + 32768), "q": (xq[k] + 32768)} for k in range(len(xi))]
        cap = run_stream(dut, ob, len(xi), ["i", "q"], ["i", "q"],
            sink_throttle=0.1, source_ready_rate=0.8)
        self.assertTrue(np.array_equal(column(cap, "i", 16), xi))
        self.assertTrue(np.array_equal(column(cap, "q", 16), xq))

class TestGoertzel(unittest.TestCase):
    def test_detects_bin(self):
        N, k = 64, 10
        def run(freq_bin):
            dut = Goertzel(N=N, k=k, data_width=16, with_csr=False)
            x = np.round(12000*np.cos(2*np.pi*freq_bin*np.arange(N)/N)).astype(int)
            cap = run_stream(dut, [{"data": int(v)} for v in x], 1, ["data"], ["data"],
                sink_throttle=0.0, source_ready_rate=1.0)
            return abs(int(to_signed(column(cap, "data"), dut.source.data.nbits)[0]))
        on  = run(k)        # tone at the Goertzel bin.
        off = run(k + 8)    # tone elsewhere.
        self.assertGreater(on, 20*max(off, 1))

class TestCorrelator(unittest.TestCase):
    def test_peak_on_alignment(self):
        code = [1, 1, 1, -1, -1, 1, -1]      # Barker-7.
        dut  = Correlator(code, data_width=16, with_csr=False)
        amp  = 4000
        # Stream: noise-ish zeros, then the code, then zeros.
        seq  = [0]*10 + [c*amp for c in code] + [0]*10
        cap  = run_stream(dut, [{"i": v, "q": 0} for v in seq], len(seq), ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        gi = np.abs(column(cap, "i", 16))
        peak = gi.max()
        # Peak (full correlation = 7*amp scaled) clearly above off-peak.
        self.assertGreater(peak, 5*np.median(gi[gi > 0]) if (gi > 0).any() else 0)

class TestIQBalance(unittest.TestCase):
    def test_corrects(self):
        # Imbalanced input: Q has gain error + leakage; correction should orthogonalize.
        n = 5000
        t = np.arange(n)
        i = np.round(10000*np.cos(2*np.pi*0.02*t)).astype(int)
        q = np.round(0.7*10000*np.sin(2*np.pi*0.02*t) + 0.2*10000*np.cos(2*np.pi*0.02*t)).astype(int)
        dut = IQBalance(data_width=16, coeff_frac=14, with_csr=False)
        # Correction to undo q' = 0.7 q_ideal + 0.2 i: c2 = 1/0.7, c1 = -0.2/0.7.
        dut.c2.reset = int(round((1/0.7)*(1 << 14)))
        dut.c1.reset = int(round((-0.2/0.7)*(1 << 14)))
        cap = run_stream(dut, [{"i": int(i[k]), "q": int(q[k])} for k in range(n)], n,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        gq = column(cap, "q", 16).astype(float)[n//2:]
        gi = column(cap, "i", 16).astype(float)[n//2:]
        ideal_q = 10000*np.sin(2*np.pi*0.02*t[n//2:])
        # Corrected Q should match the ideal quadrature (high correlation).
        c = np.corrcoef(gq, ideal_q)[0, 1]
        self.assertGreater(c, 0.99)

if __name__ == "__main__":
    unittest.main()
