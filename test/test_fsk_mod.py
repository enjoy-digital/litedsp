#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import random
import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.comm.fsk_mod  import LiteDSPFSKModulator
from litedsp.comm.fm_demod import LiteDSPFMDemod
from litedsp.comm.design   import fsk_deviation

from test.common import run_stream, column
from test.models import fsk_modulator_model

class TestFSKModulator(unittest.TestCase):
    # verify-tier: model — 2-FSK (rect), GFSK BT 0.5, 4-FSK and GMSK-style BT 0.3 at 4 samples per
    # symbol on 60 random symbols under backpressure: bit-exact I/Q; pinned latencies.
    def test_bit_exact(self):
        prng = random.Random(4)
        for bps, bt in ((1, None), (1, 0.5), (2, None), (1, 0.3)):
            with self.subTest(bps=bps, bt=bt):
                syms = [prng.randint(0, (1 << bps) - 1) for _ in range(60)]
                dut  = LiteDSPFSKModulator(bits_per_symbol=bps, sps=4, bt=bt, with_csr=False)
                cap  = run_stream(dut, [{"data": s} for s in syms], 60*4, ["data"], ["i", "q"],
                                  sink_throttle=0.2, source_ready_rate=0.7)
                ri, rq = fsk_modulator_model(syms, bps, 4, dut.taps, dut.deviation.reset.value, 0)
                self.assertEqual(column(cap, "i", 16).tolist(), ri.tolist())
                self.assertEqual(column(cap, "q", 16).tolist(), rq.tolist())
                self.assertEqual(dut.latency, 3 + (dut.fir.latency if bt else 0))

    # verify-tier: bound — 2-FSK through the FM demodulator with integrate-and-dump recovers the
    # symbols without error; the GMSK (h = 0.5, BT 0.3) phase advance per symbol is +/- pi/2
    # within 2 %; the Gaussian-filtered spectrum's 99 % bandwidth is < 0.8 of the rectangular
    # MSK one; invalid parameters.
    def test_demod_and_gmsk(self):
        prng = random.Random(5)
        syms = [prng.randint(0, 1) for _ in range(80)]
        class Loop(LiteXModule):
            def __init__(self, bt):
                self.mod   = LiteDSPFSKModulator(sps=8, bt=bt, with_csr=False)
                self.demod = LiteDSPFMDemod(with_csr=False)
                self.sink, self.source = self.mod.sink, self.demod.source
                self.comb += self.mod.source.connect(self.demod.sink)
        cap = run_stream(Loop(None), [{"data": s} for s in syms], 80*8, ["data"], ["data"],
                         sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "data", 16).astype(float)
        dec = [int(np.sum(y[k*8 + 2:(k + 1)*8]) > 0) for k in range(80)]
        self.assertEqual(dec[1:], syms[1:])
        dut = LiteDSPFSKModulator(sps=4, bt=0.3, with_csr=False)
        self.assertEqual(dut.deviation.reset.value, fsk_deviation(0.5, 4, 1))
        pattern = [1]*20 + [0]*20
        cap = run_stream(dut, [{"data": s} for s in pattern], 40*4, ["data"], ["i", "q"],
                         sink_throttle=0.0, source_ready_rate=1.0)
        z = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        ph = np.unwrap(np.angle(z))
        step_up = (ph[16*4] - ph[8*4])/8                                # Steady 1s: per symbol.
        step_dn = (ph[36*4] - ph[28*4])/8
        self.assertLessEqual(abs(step_up - math.pi/2)/(math.pi/2), 0.02)
        self.assertLessEqual(abs(step_dn + math.pi/2)/(math.pi/2), 0.02)
        def bw99(bt):
            d = LiteDSPFSKModulator(sps=8, bt=bt, with_csr=False)
            d.deviation.reset = fsk_deviation(0.5, 8, 1)
            c = run_stream(d, [{"data": s} for s in syms*2], 160*8, ["data"], ["i", "q"],
                           sink_throttle=0.0, source_ready_rate=1.0)
            zz = column(c, "i", 16) + 1j*column(c, "q", 16)
            p = np.abs(np.fft.fftshift(np.fft.fft(zz*np.hanning(len(zz)))))**2
            cdf = np.cumsum(p)/np.sum(p)
            lo, hi = np.searchsorted(cdf, 0.005), np.searchsorted(cdf, 0.995)
            return hi - lo
        self.assertLess(bw99(0.3)/bw99(None), 0.8)
        for kwargs in ({"bt": 1.5}, {"sps": 1}, {"bits_per_symbol": 5}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPFSKModulator(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
