#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.hilbert import LiteDSPHilbert
from litedsp.filter.design  import hilbert_coefficients

from test.common import run_stream, column
from test.models import fir_model

class TestHilbert(unittest.TestCase):
    def test_bit_exact_and_analytic(self):
        n_taps = 23
        dut = LiteDSPHilbert(n_taps=n_taps, data_width=16, with_csr=False)
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
        dut = LiteDSPHilbert(n_taps=31, data_width=16, with_csr=False)
        x   = np.round(15000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        cap = run_stream(dut, [{"data": int(v)} for v in x], n, ["data"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y   = (column(cap, "i", 16) + 1j*column(cap, "q", 16))[64:]
        spec = np.abs(np.fft.fft(y*np.hanning(len(y))))**2
        ff   = np.fft.fftfreq(len(y))
        pos  = spec[np.argmin(np.abs(ff - f))]
        neg  = spec[np.argmin(np.abs(ff + f))]
        self.assertGreater(pos, 30*neg)

if __name__ == "__main__":
    unittest.main()
