#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side design helpers of the communications extras."""

import math
import unittest

import numpy as np

from litedsp.filter.design import gaussian_coefficients

class TestGaussianTaps(unittest.TestCase):
    # verify-tier: bound — symmetric taps summing to unity within the quantisation, -3 dB at
    # bt * Rs within 5 % for two bandwidth-time products; invalid parameters.
    def test_gaussian(self):
        for bt in (0.3, 0.5):
            h = np.array(gaussian_coefficients(sps=8, span=6, bt=bt, data_width=16), float)
            self.assertTrue(np.array_equal(h, h[::-1]))
            self.assertLessEqual(abs(h.sum()/32768 - 1.0), 0.002)
            f = np.linspace(0, 0.5, 4001)                              # cycles per sample.
            H = np.abs(np.array([np.sum(h*np.exp(-2j*math.pi*fk*np.arange(len(h)))) for fk in f]))
            H /= H[0]
            f3 = f[np.argmin(np.abs(20*np.log10(H) + 3.0))]
            self.assertLessEqual(abs(f3 - bt/8)/(bt/8), 0.05, (bt, f3))
        with self.assertRaises(ValueError):
            gaussian_coefficients(bt=0)

if __name__ == "__main__":
    unittest.main()
