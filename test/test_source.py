#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.generation.source import LiteDSPChirp, LiteDSPNoiseSource, LiteDSPReplay

from test.common import run_stream, column, to_signed

class TestChirp(unittest.TestCase):
    def test_frequency_ramps(self):
        n = 2000
        dut = LiteDSPChirp(data_width=16, with_csr=False)
        dut.start.reset = int(0.01*(1 << 32))
        dut.rate.reset  = int(0.00005*(1 << 32))
        cap = run_stream(dut, None, n, None, ["i", "q"], source_ready_rate=1.0)
        x = to_signed(column(cap, "i"), 16) + 1j*to_signed(column(cap, "q"), 16)
        # Instantaneous frequency = angle(x[n]*conj(x[n-1])); should increase over time.
        inst = np.angle(x[1:]*np.conj(x[:-1]))
        early = inst[100:300].mean()
        late  = inst[-300:-100].mean()
        self.assertGreater(late, early + 0.05)

class TestNoiseSource(unittest.TestCase):
    def test_statistics(self):
        n = 8000
        dut = LiteDSPNoiseSource(data_width=16, n_sum=16, shift=2, with_csr=False)
        cap = run_stream(dut, None, n, None, ["i", "q"], source_ready_rate=1.0)
        i = to_signed(column(cap, "i"), 16).astype(float)
        q = to_signed(column(cap, "q"), 16).astype(float)
        self.assertLess(abs(i.mean()), i.std()*0.1)      # Zero-mean.
        self.assertGreater(i.std(), 1000)                # Non-trivial amplitude.
        self.assertLess(abs(np.corrcoef(i, q)[0, 1]), 0.1)  # I/Q independent.
        # Approximately Gaussian: kurtosis near 3 (CLT of summed PRNGs is only approximate).
        k = ((i - i.mean())**4).mean()/(i.var()**2)
        self.assertLess(abs(k - 3.0), 1.0)

class TestReplay(unittest.TestCase):
    def test_loops(self):
        samples = [(100, -100), (200, -200), (300, -300), (400, -400)]
        dut = LiteDSPReplay(samples, data_width=16, with_csr=False)
        cap = run_stream(dut, None, 10, None, ["i", "q"], source_ready_rate=1.0)
        gi = to_signed(column(cap, "i"), 16)
        self.assertEqual(list(gi[:4]), [100, 200, 300, 400])
        self.assertEqual(list(gi[4:8]), [100, 200, 300, 400])   # Looped.

if __name__ == "__main__":
    unittest.main()
