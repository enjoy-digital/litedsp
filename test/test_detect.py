#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.analysis.detect import LiteDSPEnergyDetector, LiteDSPFrequencyEstimator

from test.common import run_stream, column, stream_capture

class TestEnergyDetector(unittest.TestCase):
    def test_detects_burst(self):
        n = 3000
        rng = np.random.RandomState(0)
        sig = (rng.randint(-300, 300, n)).astype(complex)        # low noise.
        sig[1000:2000] += 6000*np.exp(1j*2*np.pi*0.05*np.arange(1000))  # burst.
        dut = LiteDSPEnergyDetector(data_width=16, avg_shift=6, threshold_log2=4, with_csr=False)
        det = []

        @passive
        def watch(dut):
            while True:
                det.append((yield dut.detect))
                yield
        cap = []
        from test.common import stream_driver
        run_simulation(dut, [
            stream_driver(dut.sink, [{"i": int(v.real), "q": int(v.imag)} for v in sig], ["i", "q"]),
            stream_capture(dut.source, cap, n - 1, ["i", "q"], ready_rate=1.0),
            watch(dut),
        ])
        det = np.array(det[:n])
        self.assertLess(det[300:900].mean(), 0.15)     # mostly quiet before burst.
        self.assertGreater(det[1200:1800].mean(), 0.7) # detected during burst.

class TestFrequencyEstimator(unittest.TestCase):
    def test_peak_and_neighbours(self):
        dut = LiteDSPFrequencyEstimator(data_width=32, index_width=8, with_csr=False)
        frame = [5, 20, 80, 200, 90, 10, 4, 4]         # peak at index 3.

        @passive
        def driver(ep):
            for k, v in enumerate(frame):
                yield ep.data.eq(v)
                yield ep.first.eq(int(k == 0))
                yield ep.last.eq(int(k == len(frame) - 1))
                yield ep.valid.eq(1)
                yield
                while (yield ep.ready) == 0:
                    yield
            yield ep.valid.eq(0)
        cap = []
        run_simulation(dut, [driver(dut.sink),
            stream_capture(dut.source, cap, 1, ["index", "peak", "left", "right"], ready_rate=1.0)])
        self.assertEqual(cap[0]["index"], 3)
        self.assertEqual(cap[0]["peak"], 200)
        self.assertEqual(cap[0]["left"], 80)
        self.assertEqual(cap[0]["right"], 90)

if __name__ == "__main__":
    unittest.main()
