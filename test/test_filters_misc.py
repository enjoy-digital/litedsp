#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.halfband    import HalfbandDecimator, HalfbandInterpolator
from litedsp.filter.hilbert     import Hilbert
from litedsp.filter.pulse_shape import PulseShaper
from litedsp.filter.design      import hilbert_coefficients

from test.common import run_stream, column
from test.models import fir_model

def tone(n, f, amp=12000):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

class TestHalfband(unittest.TestCase):
    def test_decimate_anti_alias(self):
        n = 2*300
        def run(x):
            dut = HalfbandDecimator(n_taps=23, data_width=16, with_csr=False)
            samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
            cap = run_stream(dut, samples, n//2 - 16, ["i", "q"], ["i", "q"],
                sink_throttle=0.0, source_ready_rate=1.0)
            return column(cap, "i", 16) + 1j*column(cap, "q", 16)
        inb = run(tone(n, 0.05))
        oob = run(tone(n, 0.45))   # near input Nyquist -> should be killed by halfband.
        self.assertGreater(np.abs(inb[len(inb)//2:]).mean(), 8*np.abs(oob[len(oob)//2:]).mean())

class TestHilbert(unittest.TestCase):
    def test_bit_exact_and_analytic(self):
        n_taps = 23
        dut = Hilbert(n_taps=n_taps, data_width=16, with_csr=False)
        rng = np.random.RandomState(1)
        x   = rng.randint(-20000, 20000, 400)
        cap = run_stream(dut, [{"data": int(v)} for v in x], len(x), ["data"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        gi = column(cap, "i", 16)
        gq = column(cap, "q", 16)
        delta = [0]*n_taps
        delta[(n_taps - 1)//2] = (1 << 15) - 1
        self.assertTrue(np.array_equal(gi, fir_model(x, delta)[:len(gi)]))
        self.assertTrue(np.array_equal(gq, fir_model(x, hilbert_coefficients(n_taps))[:len(gq)]))

    def test_image_rejection(self):
        # Real cosine -> analytic: positive-frequency component should dominate its mirror.
        n, f = 1024, 0.1
        dut = Hilbert(n_taps=31, data_width=16, with_csr=False)
        x   = np.round(15000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        cap = run_stream(dut, [{"data": int(v)} for v in x], n, ["data"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y   = (column(cap, "i", 16) + 1j*column(cap, "q", 16))[64:]
        spec = np.abs(np.fft.fft(y*np.hanning(len(y))))**2
        ff   = np.fft.fftfreq(len(y))
        pos  = spec[np.argmin(np.abs(ff - f))]
        neg  = spec[np.argmin(np.abs(ff + f))]
        self.assertGreater(pos, 30*neg)

class TestPulseShaper(unittest.TestCase):
    def test_pulse(self):
        sps, span = 4, 8
        dut = PulseShaper(sps=sps, span=span, beta=0.35, data_width=16, with_csr=False)
        # One nonzero symbol among zeros -> output is one RRC pulse.
        syms = [0]*4 + [16000] + [0]*8
        n_out = len(syms)*sps
        cap = run_stream(dut, [{"i": s, "q": 0} for s in syms], n_out, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16)
        self.assertGreater(np.abs(y).max(), 2000)             # Pulse present.
        self.assertLess(abs(int(np.argmax(np.abs(y))) - (4*sps + sps*span//2)), 2*sps)

if __name__ == "__main__":
    unittest.main()
