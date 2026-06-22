#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.design import firwin_lowpass, firwin_bandpass

def response_db(taps, freqs, frac_bits=15):
    taps = np.asarray(taps, dtype=float)/(1 << frac_bits)
    m    = np.arange(len(taps))
    H    = np.array([np.sum(taps*np.exp(-2j*np.pi*f*m)) for f in np.atleast_1d(freqs)])
    return 20*np.log10(np.maximum(np.abs(H), 1e-12))

class TestFIRDesign(unittest.TestCase):
    def test_bandpass_passband_and_rejection(self):
        f_low, f_high = 0.10, 0.20
        taps = firwin_bandpass(101, f_low, f_high)
        fc   = 0.5*(f_low + f_high)
        self.assertLess(abs(response_db(taps, fc)[0]),  1.0)   # ~0 dB at center.
        self.assertLess(response_db(taps, 0.0)[0],   -30)      # DC rejected.
        self.assertLess(response_db(taps, 0.40)[0],  -30)      # upper band rejected.

    def test_lowpass_still_unity_dc(self):
        taps = firwin_lowpass(63, 0.2)
        self.assertLess(abs(response_db(taps, 0.0)[0]), 0.5)   # ~0 dB at DC.
        self.assertLess(response_db(taps, 0.45)[0], -20)       # stopband.

if __name__ == "__main__":
    unittest.main()
