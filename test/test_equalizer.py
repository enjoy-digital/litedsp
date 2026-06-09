#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.equalizer import LMSEqualizer

from test.common import run_stream, column, to_signed

class TestLMSEqualizer(unittest.TestCase):
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

        dut = LMSEqualizer(n_taps=n_taps, data_width=16, wfrac=14, mu_shift=20, with_csr=False)
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

        # Equalization actually helped: residual error well below the raw ISI distortion.
        err_eq  = np.mean(np.abs(y[tail] - d[tail])**2)
        err_raw = np.mean(np.abs(x[N-1000:] - d[N-1000:])**2)
        self.assertLess(err_eq, err_raw/4)

if __name__ == "__main__":
    unittest.main()
