#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import random
import unittest

import numpy as np

from litedsp.radar.doppler import LiteDSPDopplerProcessor

from test.common import run_stream, column
from test.models import doppler_model

def columns(values, M):
    return [
        {"i": int(v.real), "q": int(v.imag), "first": int(k % M == 0), "last": int(k % M == M - 1)}
            for k, v in enumerate(values)]

class TestDopplerProcessor(unittest.TestCase):
    # verify-tier: model — six random slow-time columns (M = 16) through window, FFT, magnitude
    # (approx) or power and reorder, bit-exact under backpressure, framed per column.
    def test_bit_exact(self):
        prng = random.Random(1)
        x    = np.array([complex(prng.randint(-20000, 20000), prng.randint(-20000, 20000))
                                                                           for _ in range(7*16)])
        for magnitude, window in (("approx", "hann"), ("power", "rect")):
            with self.subTest(magnitude=magnitude, window=window):
                dut = LiteDSPDopplerProcessor(n_pulses=16, window=window, magnitude=magnitude,
                                              with_csr=False)
                cap = run_stream(dut, columns(x, 16), 6*16, ["i", "q", "first", "last"],
                                 ["data", "first", "last"],
                    sink_throttle=0.2, source_ready_rate=0.7)
                data, first, last = doppler_model(x.real, x.imag, 16, window, magnitude)
                self.assertTrue(np.array_equal(column(cap, "data"), data[:6*16]))
                self.assertEqual(column(cap, "first").tolist(), first[:6*16].tolist())
                self.assertEqual(column(cap, "last").tolist(), last[:6*16].tolist())
                self.assertIsNone(dut.latency)

    # verify-tier: bound — a target rotating d bins per CPI peaks at Doppler bin d of its range
    # column (natural order, negative bins in the upper half); Hann sidelobes <= -25 dB.
    def test_target_bin_and_sidelobes(self):
        M = 16
        cols = []
        for d in (3, 13):                                            # +3 and -3 bins.
            cols.append(np.array([12000*np.exp(2j*math.pi*d*p/M) for p in range(M)]))
        cols.append(np.zeros(M))                                    # Flush column.
        x   = np.concatenate(cols)
        dut = LiteDSPDopplerProcessor(n_pulses=M, window="hann", magnitude="approx", with_csr=False)
        cap = run_stream(dut, columns(x, M), 2*M, ["i", "q", "first", "last"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "data").astype(float).reshape(2, M)
        for row, d in zip(y, (3, 13)):
            self.assertEqual(int(np.argmax(row)), d)
            side = np.delete(row, [d - 1, d, (d + 1) % M])
            self.assertLessEqual(20*np.log10(max(np.max(side), 1)/row[d]), -25.0)

    def test_frame_error_and_invalid(self):
        prng  = random.Random(2)
        x     = np.array(
            [complex(prng.randint(-2000, 2000), prng.randint(-2000, 2000)) for _ in range(3*16)])
        beats = columns(x, 16)
        beats[20]["first"] = 1
        dut   = LiteDSPDopplerProcessor(n_pulses=16, with_csr=False)
        run_stream(dut, beats, 2*16, ["i", "q", "first", "last"], ["data"], sink_throttle=0.0,
                   source_ready_rate=1.0,
            extra=[self._read_error(dut)])
        self.assertEqual(self.error, 1)
        for kwargs in ({"n_pulses": 12}, {"magnitude": "cordic"}, {"window": "kaiser"}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPDopplerProcessor(with_csr=False, **kwargs)

    def _read_error(self, dut):
        from migen import passive
        @passive
        def gen():
            while True:
                self.error = (yield dut.frame_error)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
