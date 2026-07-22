#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.filter.fir_poly import LiteDSPFIRDecimator, LiteDSPFIRInterpolator
from litedsp.filter.design   import firwin_lowpass

from test.common import run_stream, column
from test.models import fir_decimator_model, fir_interpolator_model

class TestFIRDecimator(unittest.TestCase):
    def test_bit_exact(self):
        for architecture in ("classic", "pipelined"):
            for n_taps, R in [(16, 4), (24, 8), (12, 3), (1, 1)]:
                coeffs = ([32767] if n_taps == 1 else firwin_lowpass(n_taps, 0.4/R))
                prng   = random.Random(n_taps)
                x_i    = [prng.randint(-25000, 25000) for _ in range(R*30)]
                x_q    = [prng.randint(-25000, 25000) for _ in range(R*30)]
                dut = LiteDSPFIRDecimator(n_taps=n_taps, decimation=R, data_width=16,
                    coefficients=coeffs, with_csr=False, architecture=architecture)
                pipeline = int(architecture == "pipelined")
                self.assertEqual(dut.cycles_per_output, R + n_taps + 1 + pipeline)
                self.assertEqual(dut.latency, n_taps + 1 + pipeline)
                n_out  = len(x_i)//R
                samples = [{"i": x_i[k], "q": x_q[k]} for k in range(len(x_i))]
                cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
                    sink_throttle=0.2, source_ready_rate=0.6)
                ri = fir_decimator_model(x_i, coeffs, R)[:n_out]
                rq = fir_decimator_model(x_q, coeffs, R)[:n_out]
                self.assertTrue(np.array_equal(column(cap, "i", 16), ri),
                    f"I n={n_taps} R={R} architecture={architecture}")
                self.assertTrue(np.array_equal(column(cap, "q", 16), rq),
                    f"Q n={n_taps} R={R} architecture={architecture}")

    def test_invalid_architecture(self):
        with self.assertRaises(ValueError):
            LiteDSPFIRDecimator(architecture="invalid", with_csr=False)

class TestFIRInterpolator(unittest.TestCase):
    def test_bit_exact(self):
        for architecture in ("classic", "pipelined"):
            for n_taps, L in [(16, 4), (24, 8), (9, 3), (1, 1)]:
                coeffs = ([32767] if n_taps == 1 else
                    firwin_lowpass(n_taps, 0.4/L, gain=L))  # Gain L offsets zero-stuff loss.
                prng   = random.Random(n_taps + 1)
                x_i    = [prng.randint(-8000, 8000) for _ in range(40)]
                x_q    = [prng.randint(-8000, 8000) for _ in range(40)]
                dut    = LiteDSPFIRInterpolator(n_taps=n_taps, interpolation=L, data_width=16,
                    coefficients=coeffs, with_csr=False, architecture=architecture)
                pipeline = 2*int(architecture == "pipelined")
                self.assertEqual(dut.cycles_per_output, (n_taps + L - 1)//L + 1 + pipeline)
                self.assertEqual(dut.latency, n_taps + pipeline)
                n_out  = len(x_i)*L
                samples = [{"i": x_i[k], "q": x_q[k]} for k in range(len(x_i))]
                cap = run_stream(dut, samples, n_out, ["i", "q"], ["i", "q"],
                    sink_throttle=0.2, source_ready_rate=0.6)
                ri = fir_interpolator_model(x_i, coeffs, L)[:n_out]
                rq = fir_interpolator_model(x_q, coeffs, L)[:n_out]
                self.assertTrue(np.array_equal(column(cap, "i", 16), ri),
                    f"I n={n_taps} L={L} architecture={architecture}")
                self.assertTrue(np.array_equal(column(cap, "q", 16), rq),
                    f"Q n={n_taps} L={L} architecture={architecture}")

if __name__ == "__main__":
    unittest.main()
