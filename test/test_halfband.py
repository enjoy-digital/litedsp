#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.halfband import LiteDSPHalfbandDecimator, LiteDSPHalfbandInterpolator
from litedsp.filter.design   import halfband_coefficients

from test.common import run_stream, column
from test.models import fir_decimator_model, fir_interpolator_model

def tone(n, f, amp=12000):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

class TestHalfband(unittest.TestCase):
    def test_pruned_bit_exact(self):
        rng = np.random.RandomState(11)
        x_i = rng.randint(-12000, 12001, 80)
        x_q = rng.randint(-12000, 12001, 80)
        samples = [{"i": int(i), "q": int(q)} for i, q in zip(x_i, x_q)]

        dec_coeffs = halfband_coefficients(23, data_width=16)
        dec = LiteDSPHalfbandDecimator(n_taps=23, data_width=16, with_csr=False)
        self.assertEqual(dec.n_mac_taps, 13)
        self.assertEqual(dec.cycles_per_output, 16)  # 2 loads + 13 products + drain.
        cap = run_stream(dec, samples, len(samples)//2, ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.6)
        np.testing.assert_array_equal(column(cap, "i", 16),
            fir_decimator_model(x_i, dec_coeffs, 2))
        np.testing.assert_array_equal(column(cap, "q", 16),
            fir_decimator_model(x_q, dec_coeffs, 2))

        int_coeffs = halfband_coefficients(23, data_width=16, gain=2.0)
        interp = LiteDSPHalfbandInterpolator(n_taps=23, data_width=16, with_csr=False)
        self.assertEqual(interp.phase_mac_taps, (12, 1))
        self.assertEqual(interp.cycles_per_input, 15)  # 13 products + two emits.
        cap = run_stream(interp, samples, 2*len(samples), ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.6)
        np.testing.assert_array_equal(column(cap, "i", 16),
            fir_interpolator_model(x_i, int_coeffs, 2))
        np.testing.assert_array_equal(column(cap, "q", 16),
            fir_interpolator_model(x_q, int_coeffs, 2))

    def test_decimate_anti_alias(self):
        n = 2*300
        def run(x):
            dut = LiteDSPHalfbandDecimator(n_taps=23, data_width=16, with_csr=False)
            samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
            cap = run_stream(dut, samples, n//2 - 16, ["i", "q"], ["i", "q"],
                sink_throttle=0.0, source_ready_rate=1.0)
            return column(cap, "i", 16) + 1j*column(cap, "q", 16)
        inb = run(tone(n, 0.05))
        oob = run(tone(n, 0.45))   # near input Nyquist -> should be killed by halfband.
        self.assertGreater(np.abs(inb[len(inb)//2:]).mean(), 8*np.abs(oob[len(oob)//2:]).mean())

if __name__ == "__main__":
    unittest.main()
