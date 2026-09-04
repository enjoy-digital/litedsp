#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.level.logdb import LiteDSPLog2, LiteDSPExp2, LiteDSPLogPower

from test.common import run_stream, column
from test.models import log2_model, exp2_model

class TestLog2(unittest.TestCase):
    def test_bit_exact(self):
        dut  = LiteDSPLog2(in_width=32, frac_bits=8, with_csr=False)
        prng = random.Random(1)
        x    = [prng.randint(0, (1 << 31)) for _ in range(300)]
        cap  = run_stream(dut, [{"data": v} for v in x], len(x), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data"), log2_model(x, 32, 8)))

    def test_logpower_db(self):
        # Doubling power adds ~3 dB.
        dut = LiteDSPLogPower(in_width=32, out_frac=4, with_csr=False)
        xs  = [1 << 20, 1 << 21, 1 << 22]
        cap = run_stream(dut, [{"data": v} for v in xs], len(xs), ["data"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        db = column(cap, "data")/16.0
        self.assertAlmostEqual(db[1] - db[0], 3.01, delta=0.3)
        self.assertAlmostEqual(db[2] - db[1], 3.01, delta=0.3)

class TestLog2LUT(unittest.TestCase):
    # verify-tier: model — ROM-refined mantissa, bit-exact incl. 0 and the extremes.
    def test_bit_exact(self):
        prng = random.Random(5)
        x = [0, 1, 2, 3, (1 << 32) - 1,
             1 << 31] + [prng.randint(0, (1 << 32) - 1) for _ in range(300)]
        dut = LiteDSPLog2(in_width=32, frac_bits=8, lut=True, with_csr=False)
        cap = run_stream(dut, [{"data": v} for v in x], len(x), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data"), log2_model(x, 32, 8, lut=True)))
        self.assertEqual(dut.latency, 2)

    # verify-tier: bound — vs float log2: the linear mantissa errs by up to 0.086 (0.52 dB),
    # the ROM by half an LSB of the 8-bit fraction plus the truncated mantissa (< 2**-7).
    def test_accuracy(self):
        prng = random.Random(6)
        x = np.array([prng.randint(1, (1 << 32) - 1) for _ in range(2000)], np.int64)
        errs = {}
        for lut in (False, True):
            errs[lut] = np.max(np.abs(log2_model(x, 32, 8, lut=lut)/256 - np.log2(x)))
        self.assertGreater(errs[False], 0.05)
        self.assertLess(errs[True], 2**-7)

class TestExp2(unittest.TestCase):
    # verify-tier: model — ROM + shifts, saturation and underflow, bit-exact under backpressure.
    def test_bit_exact(self):
        prng = random.Random(7)
        v = [prng.randint(-47*256, 47*256) for _ in range(300)] + [0, 255, -1, 5*256, 6*256,
                                                                   -22*256, -30*256]
        dut = LiteDSPExp2(with_csr=False)
        cap = run_stream(dut, [{"data": x} for x in v], len(v), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data"), exp2_model(v)))
        self.assertEqual(dut.latency, 2)
        self.assertEqual(int(exp2_model([0])[0]), 1 << 20)                  # 2**0 = 1.0.
        self.assertEqual(int(exp2_model([6*256])[0]), (1 << 25) - 1)      # Saturates (2**6 > 2**5).

    # verify-tier: bound — exp2(log2_lut(x))/x within 2**-7 (the log's residual mantissa error
    # plus the exp ROM rounding) over 30 octaves of input.
    def test_log_exp_round_trip(self):
        prng = random.Random(8)
        x = np.array([prng.randint(1, (1 << 30) - 1) for _ in range(500)], np.int64)
        v = log2_model(x, 32, 8, lut=True) - 20*256                   # Scale into the output range.
        y = exp2_model(v, out_frac=20, out_width=32)
        self.assertLess(np.max(np.abs(y/x - 1.0)), 2**-7)

    def test_invalid(self):
        for kwargs in ({"frac_bits": 16}, {"out_frac": 0}, {"out_width": 20}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPExp2(with_csr=False, **kwargs)
        with self.assertRaises(ValueError):
            LiteDSPLog2(in_width=1, with_csr=False)

if __name__ == "__main__":
    unittest.main()
