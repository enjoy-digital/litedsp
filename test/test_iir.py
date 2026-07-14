#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.filter.iir_biquad import LiteDSPIIRBiquad, LiteDSPIIRBiquadCascade
from litedsp.filter.design     import biquad_sos_quantize

from test.common import run_stream, column
from test.models import iir_biquad_model, iir_cascade_model

def rbj_lowpass(fc, Q=0.707):
    """RBJ cookbook 2nd-order low-pass section [b0,b1,b2,a0,a1,a2] (fc normalized to fs)."""
    w0    = 2*np.pi*fc
    alpha = np.sin(w0)/(2*Q)
    cw    = np.cos(w0)
    b0, b1, b2 = (1 - cw)/2, 1 - cw, (1 - cw)/2
    a0, a1, a2 = 1 + alpha, -2*cw, 1 - alpha
    return [b0, b1, b2, a0, a1, a2]

class TestIIRBiquad(unittest.TestCase):
    def test_bit_exact_single(self):
        secs, frac = biquad_sos_quantize([rbj_lowpass(0.1)], frac_bits=14)
        dut  = LiteDSPIIRBiquad(data_width=16, coeffs=secs[0], frac_bits=frac, with_csr=False)
        prng = random.Random(1)
        xi = [prng.randint(-20000, 20000) for _ in range(300)]
        xq = [prng.randint(-20000, 20000) for _ in range(300)]
        samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
        cap = run_stream(dut, samples, len(xi), ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "i", 16), iir_biquad_model(xi, secs[0], frac)))
        self.assertTrue(np.array_equal(column(cap, "q", 16), iir_biquad_model(xq, secs[0], frac)))

    def test_bit_exact_cascade(self):
        secs, frac = biquad_sos_quantize([rbj_lowpass(0.1), rbj_lowpass(0.1)], frac_bits=14)
        dut  = LiteDSPIIRBiquadCascade(data_width=16, sections=secs, frac_bits=frac, with_csr=False)
        prng = random.Random(2)
        xi = [prng.randint(-15000, 15000) for _ in range(300)]
        xq = [prng.randint(-15000, 15000) for _ in range(300)]
        samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
        cap = run_stream(dut, samples, len(xi), ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "i", 16), iir_cascade_model(xi, secs, frac)))

    def test_lowpass_response(self):
        secs, frac = biquad_sos_quantize([rbj_lowpass(0.05)], frac_bits=14)
        n = 2000
        def tone(f):
            return np.round(15000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        def run(x):
            dut = LiteDSPIIRBiquad(data_width=16, coeffs=secs[0], frac_bits=frac, with_csr=False)
            cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n,
                ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
            return column(cap, "i", 16)[n//2:]
        pass_rms = run(tone(0.02)).std()    # in band.
        stop_rms = run(tone(0.30)).std()    # well above cutoff.
        self.assertGreater(pass_rms, 8000)
        self.assertLess(stop_rms, pass_rms/20)

if __name__ == "__main__":
    unittest.main()
