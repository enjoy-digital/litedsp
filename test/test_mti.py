#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import random
import unittest

import numpy as np

from litedsp.radar.mti import LiteDSPMTICanceller

from test.common import run_stream, column
from test.models import mti_model

def pulses(values, n_bins):
    """Frame ``values`` (complex per beat) as consecutive pulses of ``n_bins`` beats."""
    n = len(values)
    return [{"i": int(v.real), "q": int(v.imag), "first": int(k % n_bins == 0),
             "last": int(k % n_bins == n_bins - 1)}
            for k, v in enumerate(values)]

class TestMTICanceller(unittest.TestCase):
    # verify-tier: model — 2- and 3-pulse cancellers bit-exact on 4 random pulses of 32 bins
    # under backpressure (the 3-pulse build in both runtime modes).
    def test_bit_exact(self):
        prng = random.Random(1)
        x    = np.array([complex(prng.randint(-20000, 20000), prng.randint(-20000, 20000))
                                                                           for _ in range(4*32)])
        beats = pulses(x, 32)
        for order, mode in ((2, 0), (3, 0), (3, 1)):
            with self.subTest(order=order, mode=mode):
                dut = LiteDSPMTICanceller(n_range_bins=32, order=order, with_csr=False)
                dut.mode.reset = mode
                cap = run_stream(dut, beats, len(beats), ["i", "q", "first", "last"],
                                 ["i", "q", "first", "last"],
                    sink_throttle=0.2, source_ready_rate=0.7)
                ri, rq = mti_model(x.real, x.imag, [b["first"] for b in beats], 32, mode=mode)
                self.assertTrue(np.array_equal(column(cap, "i", 16), ri))
                self.assertTrue(np.array_equal(column(cap, "q", 16), rq))
                self.assertEqual(column(cap, "first").tolist(), [b["first"] for b in beats])
                self.assertEqual(dut.latency, 2)

    # verify-tier: bound — stationary clutter cancels exactly; a target rotating f cycles per
    # pulse is weighted |2 sin(pi f)| (2-pulse) / 4 sin^2(pi f) (3-pulse) within 1 LSB after
    # the 1/2 and 1/4 rescales.
    def test_clutter_and_target_response(self):
        n_bins, n_pulses = 16, 6
        clutter = 12000 + 3000j
        f = 0.15
        x = np.zeros(n_bins*n_pulses, np.complex128)
        for p in range(n_pulses):
            x[p*n_bins:(p + 1)*n_bins] = clutter
            x[p*n_bins + 5] = 8000*np.exp(2j*math.pi*f*p)
        beats = pulses(x, n_bins)
        for order, gain in ((2, abs(2*math.sin(math.pi*f))/2), (3, 4*math.sin(math.pi*f)**2/4)):
            with self.subTest(order=order):
                dut = LiteDSPMTICanceller(n_range_bins=n_bins, order=order, with_csr=False)
                cap = run_stream(dut, beats, len(beats), ["i", "q", "first", "last"], ["i", "q"],
                    sink_throttle=0.0, source_ready_rate=1.0)
                y = column(cap, "i", 16) + 1j*column(cap, "q", 16)
                steady = y[(order)*n_bins:]                            # After the history fills.
                clutter_cells = np.delete(np.abs(steady.reshape(-1, n_bins)), 5, axis=1)
                self.assertEqual(int(np.max(clutter_cells)), 0)
                self.assertAlmostEqual(np.mean(np.abs(steady[5::n_bins])), 8000*gain, delta=8)

    def test_bypass_and_invalid(self):
        prng  = random.Random(2)
        x     = np.array(
            [complex(prng.randint(-20000, 20000), prng.randint(-20000, 20000)) for _ in range(64)])
        beats = pulses(x, 16)
        dut   = LiteDSPMTICanceller(n_range_bins=16, with_csr=False)
        dut.bypass.reset = 1
        cap = run_stream(dut, beats, 64, ["i", "q", "first", "last"], ["i", "q"], sink_throttle=0.2,
                         source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "i", 16), x.real.astype(int)))
        for kwargs in ({"order": 4}, {"n_range_bins": 0}, {"shift": 3}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPMTICanceller(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
