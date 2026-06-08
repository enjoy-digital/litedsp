#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.rate.decimator import Decimator
from litedsp.rate.interpolator import Interpolator
from litedsp.mixing.ddc import DDC
from litedsp.mixing.duc import DUC

from test.common import run_stream, column

def tone(n, f, amp=12000, phase=0.0):
    t = np.arange(n)
    return (amp*np.exp(1j*(2*np.pi*f*t + phase)))

class TestDecimator(unittest.TestCase):
    def run_dec(self, x, factor, method):
        dut = Decimator(data_width=16, factor=factor, method=method, with_csr=False)
        n_out = len(x)//factor - dut.latency - 2
        samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
        cap = run_stream(dut, samples, max(8, n_out), ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        return column(cap, "i", 16) + 1j*column(cap, "q", 16)

    def test_anti_alias(self):
        for method in ["cic", "fir"]:
            factor, n = 4, 4*200
            inb  = self.run_dec(tone(n, 0.02), factor, method)   # in band.
            oob  = self.run_dec(tone(n, 0.20), factor, method)   # aliases / out of band.
            self.assertGreater(np.abs(inb[len(inb)//2:]).mean(),
                               8*np.abs(oob[len(oob)//2:]).mean(), f"method={method}")

class TestInterpolator(unittest.TestCase):
    def test_image_reject(self):
        # Interpolate a baseband tone; spectral images near fs/factor must be suppressed.
        factor, n = 4, 200
        dut = Interpolator(data_width=16, factor=factor, method="fir", with_csr=False)
        x   = tone(n, 0.05, amp=10000)
        samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
        cap = run_stream(dut, samples, n*factor, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y    = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        y    = y[16*factor:]                          # Skip fill.
        spec = np.abs(np.fft.fft(y*np.hanning(len(y))))**2
        f    = np.fft.fftfreq(len(y))
        want = spec[np.argmin(np.abs(f - 0.05/factor))]
        image = spec[np.argmin(np.abs(f - (1.0/factor - 0.05/factor)))]
        self.assertGreater(want, 50*image)

class TestDDC(unittest.TestCase):
    def test_tune_to_baseband(self):
        decim, n = 4, 4*400
        f = 0.10
        dut = DDC(data_width=16, decimation=decim, method="fir", with_csr=False)
        dut.nco.phase_inc.reset = int(round(f*(1 << 32))) & 0xffffffff  # down-mix by f.
        x = tone(n, f, amp=12000)
        samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
        cap = run_stream(dut, samples, n//decim - 10, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        y = y[len(y)//2:]                              # Skip transient.
        # Tone brought to DC: |mean| should dominate the AC variation.
        self.assertGreater(np.abs(y.mean()), 3000)
        self.assertLess(y.std(), np.abs(y.mean())/10 + 1)

class TestDUC(unittest.TestCase):
    def test_upconvert(self):
        interp, n = 4, 300
        f_out = 0.10
        dut = DUC(data_width=16, interpolation=interp, method="fir", with_csr=False)
        dut.nco.phase_inc.reset = int(round(f_out*(1 << 32))) & 0xffffffff
        x = np.full(n, 9000 + 0j)                      # Baseband DC.
        samples = [{"i": int(v.real), "q": int(v.imag)} for v in x]
        cap = run_stream(dut, samples, n*interp - 10, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        y = y[64:]                                     # Skip fill.
        spec = np.abs(np.fft.fft(y*np.hanning(len(y))))**2
        f    = np.fft.fftfreq(len(y))
        peak = np.argmax(spec)
        self.assertAlmostEqual(f[peak], f_out, delta=0.01)

if __name__ == "__main__":
    unittest.main()
