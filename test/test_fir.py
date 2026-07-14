#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.filter.fir import LiteDSPFIRFilter, LiteDSPFIRFilterComplex

from test.common import run_stream, column, snr_db
from test.models import fir_model, fir_complex_model

def design_lowpass(n_taps, cutoff=0.25, data_width=16):
    """Hamming-windowed-sinc low-pass, normalized to unity DC gain, quantized to Q1.(N-1)."""
    m = np.arange(n_taps) - (n_taps - 1)/2
    h = np.sinc(2*cutoff*m)*np.hamming(n_taps)
    h = h/h.sum()
    scale = (1 << (data_width - 1)) - 1
    return [int(round(c*scale)) for c in h]

class TestFIR(unittest.TestCase):
    def run_real_fir(self, coeffs, x, n_taps, data_width=16, symmetric=False):
        dut = LiteDSPFIRFilter(n_taps=n_taps, data_width=data_width, symmetric=symmetric)
        for t in range(n_taps):
            dut.coeffs[t].reset = coeffs[t]  # Signed; do not mask (would corrupt negatives).
        samples  = [{"data": int(v)} for v in x]
        captured = run_stream(dut, samples, len(x), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        return column(captured, "data", data_width)

    def test_direct_bit_exact(self):
        n_taps = 33
        coeffs = design_lowpass(n_taps)
        prng   = random.Random(1)
        x      = [prng.randint(-30000, 30000) for _ in range(256)]
        got    = self.run_real_fir(coeffs, x, n_taps, symmetric=False)
        ref    = fir_model(x, coeffs)[:len(got)]
        self.assertTrue(np.array_equal(got, ref))

    def test_symmetric_matches_direct(self):
        # Symmetric folding must be bit-identical to the direct form for symmetric taps.
        for n_taps in [32, 33]:
            coeffs = design_lowpass(n_taps)
            prng   = random.Random(2)
            x      = [prng.randint(-30000, 30000) for _ in range(256)]
            got    = self.run_real_fir(coeffs, x, n_taps, symmetric=True)
            ref    = fir_model(x, coeffs)[:len(got)]
            self.assertTrue(np.array_equal(got, ref), f"symmetric mismatch n_taps={n_taps}")

    def test_complex_bit_exact(self):
        n_taps = 17
        coeffs = design_lowpass(n_taps)
        dut    = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=16, coefficients=coeffs, with_csr=False)
        prng   = random.Random(3)
        x_i    = [prng.randint(-30000, 30000) for _ in range(200)]
        x_q    = [prng.randint(-30000, 30000) for _ in range(200)]
        samples = [{"i": x_i[k], "q": x_q[k]} for k in range(200)]
        captured = run_stream(dut, samples, 200, ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        gi = column(captured, "i", 16)
        gq = column(captured, "q", 16)
        ri, rq = fir_complex_model(x_i, x_q, coeffs)
        self.assertTrue(np.array_equal(gi, ri[:len(gi)]))
        self.assertTrue(np.array_equal(gq, rq[:len(gq)]))

    def test_lowpass_response(self):
        # In-band tone passes, out-of-band tone is strongly attenuated.
        n_taps = 63
        coeffs = design_lowpass(n_taps, cutoff=0.15)
        n      = 1024
        def tone(bin_k, amp=20000):
            t = np.arange(n)
            return (amp*np.cos(2*np.pi*bin_k*t/n)).astype(int)
        pass_in  = self.run_real_fir(coeffs, tone(40),  n_taps)   # f ~ 0.039 fs (in band).
        stop_in  = self.run_real_fir(coeffs, tone(300), n_taps)   # f ~ 0.29 fs (out of band).
        # Steady-state RMS (skip filter fill transient).
        pass_rms = np.sqrt(np.mean(pass_in[n_taps:].astype(float)**2))
        stop_rms = np.sqrt(np.mean(stop_in[n_taps:].astype(float)**2))
        self.assertGreater(pass_rms, 10000)               # In-band largely preserved.
        self.assertLess(stop_rms, pass_rms/50)            # Out-of-band >34 dB down.

if __name__ == "__main__":
    unittest.main()
