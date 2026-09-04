#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import unittest

import numpy as np

from litedsp.radar.design import (cfar_alpha, alpha_beta_from_index, tracker_gains,
                                  steering_weights,
    range_bin_metres, doppler_bin_velocity, tvg_coefficients)

class TestRadarDesign(unittest.TestCase):
    def test_cfar_alpha(self):
        # Power-domain CA-CFAR on 16 exponential cells: alpha = 16 (1e-4^(-1/16) - 1) = 12.0 (Q.8
        # 3071).
        self.assertEqual(cfar_alpha(1e-4, 16, "power"), round(16*(1e-4**(-1/16) - 1)*256))
        # Monte Carlo: exponential cells, mean of 16 training cells times alpha -> Pfa within 2x.
        prng  = np.random.default_rng(1)
        cells = prng.exponential(1.0, (200000, 17))
        thr   = cells[:, :16].mean(axis=1)*cfar_alpha(1e-2, 16, "power")/256
        self.assertAlmostEqual(np.mean(cells[:, 16] > thr), 1e-2, delta=5e-3)
        mag = np.abs(prng.normal(size=(200000, 2)).view(np.complex128)[:, 0])
        thr = mag.mean()*cfar_alpha(1e-3, 16, "magnitude")/256
        self.assertAlmostEqual(np.mean(mag > thr), 1e-3, delta=1e-3)
        for kwargs in ({"pfa": 0.0}, {"n_train_cells": 0}, {"domain": "log"}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                cfar_alpha(**kwargs)

    def test_tracking_gains(self):
        alpha, beta = alpha_beta_from_index(0.5)
        self.assertTrue(0 < beta < alpha < 1)
        a1, _ = alpha_beta_from_index(4.0)
        self.assertGreater(a1, alpha)                                  # More process noise: faster.
        self.assertEqual(tracker_gains(0.5, 0.25, 8), (128, 64))
        with self.assertRaises(ValueError):
            alpha_beta_from_index(0.0)

    def test_steering_weights(self):
        re, im = steering_weights(4, 0.0, weight_frac=14)
        self.assertEqual(re, [4096]*4)                                # Broadside average 1/4.
        self.assertEqual(im, [0]*4)
        re, im = steering_weights(4, 30.0, 0.5, "rect", 14)
        w = (np.array(re) + 1j*np.array(im))/2**14
        theta = math.radians(30)
        self.assertLess(abs(np.sum(w*np.exp(2j*math.pi*0.5*np.arange(4)*math.sin(theta))) - 1),
                        0.01)

    def test_units_and_tvg(self):
        self.assertAlmostEqual(range_bin_metres(1e6), 149.896, places=2)
        self.assertAlmostEqual(doppler_bin_velocity(1, 16, 1000.0, 0.03), 1000/16*0.015)
        self.assertAlmostEqual(doppler_bin_velocity(15, 16, 1000.0, 0.03), -1000/16*0.015)
        g0, k_log, k_lin = tvg_coefficients(40.0, 0.0, 0.0, 8)
        self.assertEqual((g0, k_log, k_lin), (0, 512, 0))             # 40 dB/decade = r^2.
        self.assertEqual(tvg_coefficients(20.0, 6.0206, 12.0412, 8)[1:], (256, 256))

if __name__ == "__main__":
    unittest.main()
