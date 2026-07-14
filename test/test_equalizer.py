#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.equalizer import LiteDSPLMSEqualizer

from test.common import run_stream, column, to_signed

class TestLMSEqualizer(unittest.TestCase):
    # verify-tier: bound — converged MSE gated against the Wiener floor: for h = [1, 0.45,
    # -0.25, 0.1], the optimal 7-tap delay-3 linear equalizer has MMSE = 0.135*amp**2 (solve
    # R w = p with R[a,b] = Es*sum_m h[m]*h[m+a-b], p[a] = Es*h[delay-a], Es = 2*amp**2,
    # MMSE = Es - w.p). The LMS (mu_shift=20) measured at 0.99x MMSE (LITEDSP_SEED=0);
    # gate at 1.5x. Eye opening measured at 0.25*amp; gate at amp/8.
    def test_trained_isi(self):
        n_taps = 7
        delay  = n_taps//2
        amp    = 7000
        N      = 6000
        rng    = np.random.RandomState(0)
        sym    = (2*rng.randint(0, 2, N) - 1) + 1j*(2*rng.randint(0, 2, N) - 1)   # QPSK +/-1+/-1j.
        sym   *= amp
        h      = np.array([1.0, 0.45, -0.25, 0.1])                                # ISI channel.
        x      = np.convolve(sym, h)[:N]
        d      = np.concatenate([np.zeros(delay, complex), sym])[:N]              # Desired = delayed symbols.

        dut = LiteDSPLMSEqualizer(n_taps=n_taps, data_width=16, wfrac=14, mu_shift=20, with_csr=False)
        samples = [{"i": int(round(x[k].real)), "q": int(round(x[k].imag)),
                    "d_i": int(round(d[k].real)), "d_q": int(round(d[k].imag))} for k in range(N)]
        cap = run_stream(dut, samples, N, ["i", "q", "d_i", "d_q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y = to_signed(column(cap, "i"), 16) + 1j*to_signed(column(cap, "q"), 16)

        # After convergence: decisions on the equalized output match the (delayed) symbols.
        tail = slice(N - 1000, len(y))
        dec  = np.sign(y[tail].real) + 1j*np.sign(y[tail].imag)
        ref  = np.sign(d[tail].real) + 1j*np.sign(d[tail].imag)
        ser  = np.mean(dec != ref)
        self.assertLess(ser, 0.02)

        # Equalization actually helped: residual error well below the raw ISI distortion
        # (measured ratio ~32x at LITEDSP_SEED=0; gate at 16x).
        err_eq  = np.mean(np.abs(y[tail] - d[tail])**2)
        err_raw = np.mean(np.abs(x[N-1000:] - d[N-1000:])**2)
        self.assertLess(err_eq, err_raw/16)

        # Converged MSE sits at the Wiener floor (derivation above the test).
        self.assertLess(err_eq, 1.5*0.135*amp**2)

        # Eye opening: every post-convergence decision clears the slicer threshold by amp/8.
        eye = min(np.min(np.abs(y[tail].real)), np.min(np.abs(y[tail].imag)))
        self.assertGreater(eye, amp/8)

if __name__ == "__main__":
    unittest.main()
