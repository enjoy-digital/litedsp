#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Audio-quality metrics in char/metrics.py (THD, THD+N)."""

import unittest

import numpy as np

from char.metrics import thd_db, thd_n_db, sinad_db

class TestTHD(unittest.TestCase):
    def test_thd_and_thd_n(self):
        n, f = 8192, 0.0173
        t    = np.arange(n)
        pure = np.sin(2*np.pi*f*t)
        self.assertLess(thd_db(pure, f), -100)
        dist = pure + 0.01*np.sin(2*np.pi*2*f*t)                  # -40 dB second harmonic.
        self.assertAlmostEqual(thd_db(dist, f), -40.0, delta=0.2)
        noisy = pure + 1e-3*np.random.default_rng(1).standard_normal(n)
        self.assertAlmostEqual(thd_n_db(noisy, f), 20*np.log10(1e-3/np.sqrt(0.5)), delta=0.5)
        self.assertAlmostEqual(thd_n_db(noisy, f), -sinad_db(noisy, f), places=9)

    def test_thd_n_band(self):
        n, f = 8192, 0.0173
        t    = np.arange(n)
        x    = np.sin(2*np.pi*f*t) + 1e-3*np.sin(2*np.pi*0.4*t)   # Out-of-band spur at 0.4.
        self.assertAlmostEqual(thd_n_db(x, f), 20*np.log10(1e-3), delta=0.2)
        self.assertLess(thd_n_db(x, f, band=(0.0, 0.2)), -100)

    def test_thd_folds_harmonics(self):
        n, f = 4096, 0.2                                          # 3rd harmonic folds to 0.4.
        t    = np.arange(n)
        x    = np.sin(2*np.pi*f*t) + 0.001*np.sin(2*np.pi*0.4*t)
        self.assertAlmostEqual(thd_db(x, f), -60.0, delta=0.3)

if __name__ == "__main__":
    unittest.main()
