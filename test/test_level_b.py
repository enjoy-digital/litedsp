#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.level.logdb   import Log2, LogPower
from litedsp.level.clipper import Clipper
from litedsp.level.peak    import EnvelopeDetector
from litedsp.level.squelch import Squelch
from litedsp.level.agc     import AGC

from test.common import run_stream, column
from test.models import log2_model

def tone(n, f, amp):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

class TestLog2(unittest.TestCase):
    def test_bit_exact(self):
        dut  = Log2(in_width=32, frac_bits=8, with_csr=False)
        prng = random.Random(1)
        x    = [prng.randint(0, (1 << 31)) for _ in range(300)]
        cap  = run_stream(dut, [{"data": v} for v in x], len(x), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data"), log2_model(x, 32, 8)))

    def test_logpower_db(self):
        # Doubling power adds ~3 dB.
        dut = LogPower(in_width=32, out_frac=4, with_csr=False)
        xs  = [1 << 20, 1 << 21, 1 << 22]
        cap = run_stream(dut, [{"data": v} for v in xs], len(xs), ["data"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        db = column(cap, "data")/16.0
        self.assertAlmostEqual(db[1] - db[0], 3.01, delta=0.3)
        self.assertAlmostEqual(db[2] - db[1], 3.01, delta=0.3)

class TestClipper(unittest.TestCase):
    def test_clamp(self):
        dut = Clipper(data_width=16, with_csr=False)
        thr = 10000
        dut.threshold.reset = thr
        prng = random.Random(2)
        xi = [prng.randint(-32000, 32000) for _ in range(200)]
        xq = [prng.randint(-32000, 32000) for _ in range(200)]
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
            len(xi), ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        gi = column(cap, "i", 16)
        self.assertTrue(np.array_equal(gi, np.clip(xi, -thr, thr)))

class TestEnvelope(unittest.TestCase):
    def test_tracks_amplitude(self):
        n = 2000
        amp = 9000
        dut = EnvelopeDetector(data_width=16, attack=3, release=3, with_csr=False)
        x   = tone(n, 0.01, amp)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n, ["i", "q"], ["data"], sink_throttle=0.0, source_ready_rate=1.0)
        env = column(cap, "data")[n//2:]
        self.assertAlmostEqual(env.mean(), amp, delta=amp*0.15)

class TestSquelch(unittest.TestCase):
    def test_gates(self):
        dut = Squelch(data_width=16, with_csr=False)
        dut.open_threshold.reset  = 5000**2
        dut.close_threshold.reset = 3000**2
        loud  = [{"i": 8000, "q": 0} for _ in range(20)]
        quiet = [{"i": 100,  "q": 0} for _ in range(20)]
        cap = run_stream(dut, loud + quiet, 40, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        gi = column(cap, "i", 16)
        self.assertGreater(np.abs(gi[5:18]).mean(), 5000)   # loud passes.
        self.assertEqual(np.abs(gi[25:]).sum(), 0)          # quiet muted.

class TestAGC(unittest.TestCase):
    def test_converges(self):
        n = 6000
        target = 8000
        dut = AGC(data_width=16, gain_frac=8, mu=6, with_csr=False)
        dut.target.reset = target
        x = tone(n, 0.02, 1500)                              # weak input.
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        self.assertAlmostEqual(np.abs(y[-500:]).mean(), target, delta=target*0.2)

if __name__ == "__main__":
    unittest.main()
