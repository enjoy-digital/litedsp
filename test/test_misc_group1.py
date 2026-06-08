#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation

from litedsp.numeric          import ISqrt
from litedsp.level.rms        import RMS
from litedsp.stream.ops       import Conjugate, SwapIQ, Negate
from litedsp.stream.split     import Split
from litedsp.stream.delay     import Delay
from litedsp.comm.slicer      import Slicer
from litedsp.comm.diff        import DifferentialEncoder, DifferentialDecoder
from litedsp.comm.phase_detect import PhaseDetect

from test.common import run_stream, column, stream_driver, stream_capture, to_signed
from test.models import isqrt_model

class TestISqrt(unittest.TestCase):
    def test_bit_exact(self):
        dut  = ISqrt(in_width=32, with_csr=False)
        prng = random.Random(1)
        x    = [prng.randint(0, (1 << 32) - 1) for _ in range(300)]
        cap  = run_stream(dut, [{"data": v} for v in x], len(x), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data"), isqrt_model(x)))

class TestRMS(unittest.TestCase):
    def test_constant(self):
        dut = RMS(data_width=16, window_log2=5, with_csr=False)
        i, q = 3000, 4000   # |x| = 5000 exactly.
        n = (1 << 5)*4
        cap = run_stream(dut, [{"i": i, "q": q} for _ in range(n)], 3, ["i", "q"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        self.assertTrue(all(abs(int(v) - 5000) <= 1 for v in column(cap, "data")))

class TestStreamOps(unittest.TestCase):
    def run_op(self, cls, xi, xq):
        dut = cls(data_width=16)
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))], len(xi),
            ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        return column(cap, "i", 16), column(cap, "q", 16)

    def test_ops(self):
        prng = random.Random(2)
        xi = [prng.randint(-30000, 30000) for _ in range(100)]
        xq = [prng.randint(-30000, 30000) for _ in range(100)]
        gi, gq = self.run_op(Conjugate, xi, xq)
        self.assertTrue(np.array_equal(gi, xi) and np.array_equal(gq, -np.array(xq)))
        gi, gq = self.run_op(SwapIQ, xi, xq)
        self.assertTrue(np.array_equal(gi, xq) and np.array_equal(gq, xi))
        gi, gq = self.run_op(Negate, xi, xq)
        self.assertTrue(np.array_equal(gi, -np.array(xi)) and np.array_equal(gq, -np.array(xq)))

class TestSplit(unittest.TestCase):
    def test_duplicate(self):
        dut = Split(n=3, data_width=16)
        prng = random.Random(3)
        xi = [prng.randint(-1000, 1000) for _ in range(60)]
        xq = [prng.randint(-1000, 1000) for _ in range(60)]
        caps = [[] for _ in range(3)]
        run_simulation(dut, [
            stream_driver(dut.sink, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
                ["i", "q"], throttle=0.1),
            *[stream_capture(dut.sources[j], caps[j], len(xi), ["i", "q"], seed=j, ready_rate=0.6 + 0.1*j)
              for j in range(3)],
        ])
        for j in range(3):
            self.assertTrue(np.array_equal(column(caps[j], "i", 16), xi))

class TestDelay(unittest.TestCase):
    def test_aligns(self):
        depth = 5
        dut = Delay(depth=depth, data_width=16)
        prng = random.Random(4)
        xi = [prng.randint(-1000, 1000) for _ in range(80)]
        cap = run_stream(dut, [{"i": xi[k], "q": 0} for k in range(len(xi))], len(xi) - depth,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        gi = column(cap, "i", 16)
        self.assertTrue(np.array_equal(gi, np.array(xi[:len(gi)])))  # No bubbles -> pure delay.

class TestSlicer(unittest.TestCase):
    def test_qpsk(self):
        dut = Slicer(data_width=16, bits_per_axis=1, spacing=8000, with_csr=False)
        pts = [(5000, -7000), (-3000, 2000), (9000, 9000), (-1000, -1000)]
        cap = run_stream(dut, [{"i": i, "q": q} for i, q in pts], len(pts), ["i", "q"],
            ["i", "q", "symbol"], sink_throttle=0.0, source_ready_rate=1.0)
        gi = column(cap, "i", 16)
        gq = column(cap, "q", 16)
        self.assertTrue(np.array_equal(np.sign(gi), [1, -1, 1, -1]))
        self.assertTrue(np.array_equal(np.sign(gq), [-1, 1, 1, -1]))

class TestDifferential(unittest.TestCase):
    def test_roundtrip(self):
        M = 4
        enc = DifferentialEncoder(modulus=M, with_csr=False)
        prng = random.Random(5)
        syms = [prng.randint(0, M - 1) for _ in range(80)]
        cap_e = run_stream(enc, [{"data": s} for s in syms], len(syms), ["data"], ["data"],
            sink_throttle=0.1, source_ready_rate=0.8)
        enc_out = list(column(cap_e, "data"))
        dec = DifferentialDecoder(modulus=M, with_csr=False)
        cap_d = run_stream(dec, [{"data": int(s)} for s in enc_out], len(enc_out), ["data"], ["data"],
            sink_throttle=0.1, source_ready_rate=0.8)
        dec_out = list(column(cap_d, "data"))
        # First decoded symbol depends on initial state; rest must match.
        self.assertEqual(dec_out[1:], syms[1:len(dec_out)])

class TestPhaseDetect(unittest.TestCase):
    def test_angle(self):
        dut = PhaseDetect(data_width=16, angle_width=16, with_csr=False)
        import numpy as np
        angs = np.linspace(-np.pi*0.9, np.pi*0.9, 64)
        pts  = [(int(12000*np.cos(a)), int(12000*np.sin(a))) for a in angs]
        cap  = run_stream(dut, [{"i": i, "q": q} for i, q in pts], len(pts), ["i", "q"], ["angle"],
            sink_throttle=0.0, source_ready_rate=1.0)
        got = to_signed(column(cap, "angle"), 16)/(1 << 16)*2*np.pi
        err = np.angle(np.exp(1j*(got - angs)))
        self.assertLess(np.abs(err).max(), 0.01)

if __name__ == "__main__":
    unittest.main()
